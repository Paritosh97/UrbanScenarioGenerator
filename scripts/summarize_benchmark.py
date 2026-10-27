"""Turn ``benchmark.jsonl`` into the tables of the evaluation section (markdown + CSV).

    python scripts/summarize_benchmark.py ../paper/results/benchmark.jsonl ../paper/results

Proportions carry Wilson 95% intervals; paired comparisons between pipelines use an exact two-sided sign test on the
(prompt, repetition) pairs where the two pipelines differ.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def pct(k: int, n: int) -> str:
    if n == 0:
        return "-"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% [{max(0, 100 * lo):.0f}, {min(100, 100 * hi):.0f}]"


def sign_test(a_only: int, b_only: int) -> float:
    n = a_only + b_only
    if n == 0:
        return 1.0
    k = min(a_only, b_only)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


LABEL = {"baseline": "keyword baseline (no model)", "T0": "T0 bare prompt template (1 call, no tools, no repair)", 0: "L0 script + task helpers", 1: "L1 specification (library)", 2: "L2 specification + own definitions",
         "0v": "L0 + map image", "1v": "L1 + map image", "2v": "L2 + map image"}
FAMILY = lambda r: "mixed (several constraints, look/wait)" if r["id"].startswith("mixed") else "real map (Munich)" if r["id"].startswith("real") else "the 7 named types (synthetic city)"  # noqa: E731


def main(src: str, outdir: str) -> None:
    rows = [json.loads(line) for line in Path(src).read_text(encoding="utf-8").splitlines() if line.strip()]
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    levels = [lv for lv in ("baseline", "T0", 0, 1, 2, "0v", "1v", "2v") if any(r["level"] == lv for r in rows)]
    models = sorted({r["model"] for r in rows if r.get("model")})
    maps = sorted({r["map"] for r in rows})
    md: list[str] = ["# Benchmark results\n", f"{len(rows)} runs on {len(maps)} map(s) ({', '.join(maps)}); "
                     f"models: {', '.join(models) if models else 'Qwen3.5-4B Q4_K_M'} (LM Studio llama.cpp), temperature 0.2.\n"]

    def block(title, selector):
        md.append(f"\n## {title}\n")
        md.append("| pipeline | runs | accepted (model alone) | valid output (with safety nets) | first try (no repair) | adherent | axes recall | nominal walker ok | mean steps | mean s |")
        md.append("|---|---|---|---|---|---|---|---|---|---|")
        for lv in levels:
            rs = [r for r in rows if r["level"] == lv and selector(r)]
            n = len(rs)
            if not n:
                continue
            acc = [r for r in rs if r["accepted"]]
            md.append(f"| {LABEL[lv]} | {n} | {pct(len(acc), n)} | {pct(sum(r.get('valid_output', r['accepted']) for r in rs), n)} | {pct(sum(r['first_try'] for r in rs), n)} | {pct(sum(r['adherent'] for r in rs), n)} | "
                      f"{mean(r['recall'] for r in rs):.2f} | {pct(sum(r['nominal_ok'] for r in acc), len(acc))} | {mean(r['steps'] for r in rs):.1f} | {mean(r['seconds'] for r in rs):.0f} |")

    block("All prompts", lambda r: True)
    for fam in sorted({FAMILY(r) for r in rows}):
        block(fam, lambda r, fam=fam: FAMILY(r) == fam)

    if len(maps) > 1:
        for m in maps:
            block(f"Map: {m}", lambda r, m=m: r["map"] == m)
    if len(models) > 1:
        for mo in models:
            block(f"Model: {mo}", lambda r, mo=mo: r.get("model") in (mo, None))

    # ---- per named type
    md.append("\n## Adherence per scenario type (all pipelines with a model)\n")
    types = sorted({r["type"] for r in rows})
    md.append("| type | " + " | ".join(LABEL[lv] for lv in levels) + " |")
    md.append("|---|" + "---|" * len(levels))
    for ty in types:
        cells = []
        for lv in levels:
            rs = [r for r in rows if r["level"] == lv and r["type"] == ty]
            cells.append(pct(sum(r["adherent"] for r in rs), len(rs)) if rs else "-")
        md.append(f"| {ty} | " + " | ".join(cells) + " |")

    # ---- paired comparisons
    md.append("\n## Paired comparisons (same prompt and repetition)\n")
    md.append("| comparison | metric | A only | B only | both | neither | sign-test p |")
    md.append("|---|---|---|---|---|---|---|")
    if len(models) > 1:                                   # pairs are compared within one model
        md.append("\n(Computed for the first model only; filter the JSONL by `model` for the others.)\n")
        rows = [r for r in rows if r.get("model") in (models[0], None)]
    by = {(r["id"], r["level"], r.get("rep", 0)): r for r in rows}
    keys = sorted({(r["id"], r.get("rep", 0)) for r in rows if r["level"] in ("T0", 0, 1, 2, "0v", "1v", "2v")})
    pairs = ([("T0", 0)] if any(r["level"] == "T0" for r in rows) else []) + [(0, 1), (0, 2), (1, 2)] + [(x, f"{x}v") for x in (0, 1, 2) if any(r["level"] == f"{x}v" for r in rows)]
    for a, b in pairs:
        for metric in ("accepted", "first_try", "adherent"):
            ao = bo = bb = nn = 0
            for pid, rep in keys:
                ra, rb = by.get((pid, a, rep)), by.get((pid, b, rep))
                if not ra or not rb:
                    continue
                x, y = bool(ra[metric]), bool(rb[metric])
                ao += x and not y; bo += y and not x; bb += x and y; nn += (not x) and (not y)
            md.append(f"| A={LABEL[a].split(' ')[0] + (' text' if not str(a).endswith('v') else ' image')}, B={LABEL[b].split(' ')[0] + (' image' if str(b).endswith('v') else '')} | {metric} | {ao} | {bo} | {bb} | {nn} | {sign_test(ao, bo):.3f} |")

    # ---- repetition spread
    reps = sorted({r.get("rep", 0) for r in rows if r["level"] in (0, 1, 2)})
    if len(reps) > 1:
        md.append("\n## Spread across repetitions (accepted / adherent rate per repetition)\n")
        md.append("| pipeline | " + " | ".join(f"rep {i}" for i in reps) + " | mean ± sd (adherent) |")
        md.append("|---|" + "---|" * (len(reps) + 1))
        for lv in (0, 1, 2):
            cells, ad = [], []
            for rp in reps:
                rs = [r for r in rows if r["level"] == lv and r.get("rep", 0) == rp]
                if rs:
                    cells.append(f"{sum(r['accepted'] for r in rs)}/{len(rs)} · {sum(r['adherent'] for r in rs)}/{len(rs)}")
                    ad.append(sum(r["adherent"] for r in rs) / len(rs))
                else:
                    cells.append("-")
            if ad:
                m = mean(ad)
                sd = math.sqrt(sum((x - m) ** 2 for x in ad) / max(1, len(ad) - 1))
                md.append(f"| {LABEL[lv]} | " + " | ".join(cells) + f" | {100 * m:.0f}% ± {100 * sd:.0f} |")

    # ---- what the specification pipelines use
    md.append("\n## What the generated specifications contain\n")
    ops = Counter()
    n_def = 0
    for r in rows:
        if r["level"] in (1, 2, "1v", "2v") and r["accepted"]:
            ops.update(r.get("ops", []))
            n_def += r.get("n_defs", 0) > 0
    md.append("Operators used in accepted L1/L2 scenarios: " + (", ".join(f"{k} ({v})" for k, v in ops.most_common()) or "-"))
    md.append(f"\nL2 scenarios that defined their own definitions: {sum(1 for r in rows if r['level'] == 2 and r['accepted'] and r.get('n_defs', 0) > 0)} "
              f"of {sum(1 for r in rows if r['level'] == 2 and r['accepted'])} accepted.")

    # ---- failures
    md.append("\n## Why runs failed\n")
    for lv in [x for x in (0, 1, 2, "0v", "1v", "2v") if any(r["level"] == x for r in rows)]:
        c = Counter(r["reason"] or "accepted but not adherent" for r in rows if r["level"] == lv and not r["accepted"])
        if c:
            md.append(f"**{LABEL[lv]}**: " + "; ".join(f"{k} ×{v}" for k, v in c.most_common(6)))
    fb = defaultdict(Counter)
    for r in rows:
        if r["level"] in (0, 1, 2, "0v", "1v", "2v"):
            for f in r.get("feedback", []):
                key = f.split(":", 2)
                fb[r["level"]][(key[0] + ": " + (key[1] if len(key) > 1 else ""))[:110].strip()] += 1
    for lv, c in fb.items():
        md.append(f"\nMost frequent rejection feedback, {LABEL[lv]}:")
        for k, v in c.most_common(5):
            md.append(f"- ×{v} {k}")

    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with (out / "runs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        cols = ["id", "type", "map", "level", "rep", "accepted", "first_try", "adherent", "axes_exact", "recall", "atoms_ok", "nominal_ok",
                "attempts", "spec_attempts", "steps", "seconds", "n_tasks", "n_defs", "formula_nodes", "warnings", "reason"]
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
    print("\n".join(md[:60]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../paper/results/benchmark.jsonl", sys.argv[2] if len(sys.argv) > 2 else "../paper/results")
