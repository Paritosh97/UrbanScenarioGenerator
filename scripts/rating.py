"""Human rating of prompt-scenario match (the Text2Scenario protocol: raters score 0-1 in steps of 0.1 how well a scenario fits its text).

    # 1. sample accepted scenarios (needs a benchmark run made with --save-specs) and blind them
    python scripts/rating.py sheet --runs ../paper/results/benchmark.jsonl --prompts eval/prompts_sophia.json eval/prompts_munich.json \\
        --n 60 --raters 15 --out ../paper/rating
    # 2. raters fill ../paper/rating/ratings.csv (copy of ratings_template.csv): item_id, rater, score
    # 3. analyse
    python scripts/rating.py summary --dir ../paper/rating

Items are shuffled and carry no pipeline / model / level, only the prompt and the task instructions; ``key.csv`` links them back. The scenario
itself is ``scenarios/<item>.xosc`` (open it in the player, ``usg app`` -> /player, or load the file there) - raters should play or watch it,
not just read the text. Sampling is stratified by pipeline level, map and model so every cell gets about the same number of items.

Ethics: check whether your institution needs consent / approval for the rater study before running step 2.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

SCORES = [round(0.1 * i, 1) for i in range(11)]


def cmd_sheet(a) -> int:
    texts = {}
    for p in a.prompts:
        for q in json.loads(Path(p).read_text(encoding="utf-8"))["prompts"]:
            texts[q["id"]] = q["text"]
    runs = [json.loads(line) for line in Path(a.runs).read_text(encoding="utf-8").splitlines() if line.strip()]
    pool = [r for r in runs if r.get("accepted") and r.get("spec") and r["id"] in texts and r["level"] != "baseline"]
    if not pool:
        print("no accepted runs with a stored spec: run scripts/benchmark.py with --save-specs")
        return 1
    rng = random.Random(a.seed)
    cells = defaultdict(list)
    for r in pool:
        cells[(str(r["level"]), r["map"], r.get("model"))].append(r)
    for v in cells.values():
        rng.shuffle(v)
    chosen = []
    while len(chosen) < a.n and any(cells.values()):                 # round robin over the cells
        for k in sorted(cells, key=str):
            if cells[k] and len(chosen) < a.n:
                chosen.append(cells[k].pop())
    rng.shuffle(chosen)
    out = Path(a.out)
    (out / "scenarios").mkdir(parents=True, exist_ok=True)
    with (out / "items.csv").open("w", newline="", encoding="utf-8") as fi, (out / "key.csv").open("w", newline="", encoding="utf-8") as fk:
        wi, wk = csv.writer(fi), csv.writer(fk)
        wi.writerow(["item_id", "prompt", "task_instructions", "scenario_file"])
        wk.writerow(["item_id", "run_id", "level", "map", "model", "rep"])
        for i, r in enumerate(chosen, 1):
            item = f"item{i:03d}"
            (out / "scenarios" / f"{item}.xosc").write_text(r.get("xosc") or "", encoding="utf-8")
            instr = " | ".join(t.get("instruction") or t["name"] for t in r["spec"]["tasks"])
            wi.writerow([item, texts[r["id"]], instr, f"scenarios/{item}.xosc"])
            wk.writerow([item, r["id"], r["level"], r["map"], r.get("model"), r.get("rep", 0)])
    with (out / "ratings_template.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "rater", "score"])
        for k in range(1, a.raters + 1):
            for i in range(1, len(chosen) + 1):
                w.writerow([f"item{i:03d}", f"R{k:02d}", ""])
    (out / "INSTRUCTIONS.md").write_text(
        "# Rating instructions\n\nFor each item read the prompt, then play or watch the scenario file. Score how well the scenario matches "
        "the prompt: 0.0 = does not match at all, 1.0 = matches completely (steps of 0.1). Judge the match to the text only - not graphics, "
        "not how hard the task is. Do not guess which system made it; the order is random.\n", encoding="utf-8")
    print(f"{len(chosen)} items from {len(cells)} cells -> {out}")
    return 0


def _icc2k(table: list[list[float]]) -> float:
    """ICC(2,k): agreement of the mean of k raters (rows = items, columns = raters, complete data only)."""
    n, k = len(table), len(table[0])
    if n < 2 or k < 2:
        return float("nan")
    gm = sum(map(sum, table)) / (n * k)
    rm = [sum(r) / k for r in table]
    cm = [sum(table[i][j] for i in range(n)) / n for j in range(k)]
    ssr = k * sum((m - gm) ** 2 for m in rm)
    ssc = n * sum((m - gm) ** 2 for m in cm)
    sst = sum((table[i][j] - gm) ** 2 for i in range(n) for j in range(k))
    sse = sst - ssr - ssc
    msr, msc, mse = ssr / (n - 1), ssc / (k - 1), sse / ((n - 1) * (k - 1))
    return (msr - mse) / (msr + (msc - mse) / n) if (msr + (msc - mse) / n) else float("nan")


def cmd_summary(a) -> int:
    d = Path(a.dir)
    key = {r["item_id"]: r for r in csv.DictReader((d / "key.csv").open(encoding="utf-8"))}
    scores = defaultdict(dict)
    for r in csv.DictReader((d / "ratings.csv").open(encoding="utf-8")):
        if r["score"].strip() == "":
            continue
        s = round(float(r["score"]), 1)
        if s not in SCORES:
            print(f"ignored {r['item_id']}/{r['rater']}: score {s} is not in 0.0..1.0 steps of 0.1")
            continue
        scores[r["item_id"]][r["rater"]] = s
    raters = sorted({k for v in scores.values() for k in v})
    complete = [[v[r] for r in raters] for v in scores.values() if all(r in v for r in raters)]
    item_mean = {i: st.mean(v.values()) for i, v in scores.items()}
    rng = random.Random(0)

    def ci(vals):
        if len(vals) < 2:
            return (float("nan"), float("nan"))
        bs = sorted(st.mean(rng.choices(vals, k=len(vals))) for _ in range(2000))
        return (bs[50], bs[1949])

    lines = ["# Human rating of prompt-scenario match", "",
             f"{len(scores)} items, {len(raters)} raters; score 0-1 (steps of 0.1). ICC(2,k) over the {len(complete)} fully rated items: "
             f"{_icc2k(complete):.2f}. Bootstrap 95% intervals over items.", ""]
    for field in ("level", "map", "model"):
        lines += [f"## By {field}", "", f"| {field} | items | mean score | 95% CI |", "|---|---|---|---|"]
        groups = defaultdict(list)
        for i, m in item_mean.items():
            groups[key[i][field]].append(m)
        for g, vals in sorted(groups.items(), key=lambda kv: str(kv[0])):
            lo, hi = ci(vals)
            lines.append(f"| {g} | {len(vals)} | {st.mean(vals):.2f} | [{lo:.2f}, {hi:.2f}] |")
        lines.append("")
    (d / "rating_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--runs", required=True)
    s.add_argument("--prompts", nargs="+", required=True)
    s.add_argument("--n", type=int, default=60)
    s.add_argument("--raters", type=int, default=15)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--out", required=True)
    m = sub.add_parser("summary")
    m.add_argument("--dir", required=True)
    a = ap.parse_args()
    return cmd_sheet(a) if a.cmd == "sheet" else cmd_summary(a)


if __name__ == "__main__":
    sys.exit(main())
