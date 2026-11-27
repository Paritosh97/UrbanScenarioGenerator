"""Generate the Paris / Munich dataset (CPU only; resumable per area and part).

    python scripts/window_data.py --workers 12                     # full dataset into train/data_city
    python scripts/window_data.py --scale 0.01 --out train/probe   # small check run

Splits (rows = records):
    sft 6000, rl 2000     training areas (marais, batignolles, montparnasse; maxvorstadt, haidhausen, schwabing); rl uses other windows
    val 500               the eastern strip of the training areas, 30 m away from every training window
    test 1000             the two centre areas, never used otherwise (known combinations, new streets)
    test_heldout 300      the two centre areas, only the held-out combinations
    test_long 200         the two centre areas, 4 or 5 steps
Output: <out>/<split>.jsonl, <out>/windows.json, <out>/STATS.md. Parts are kept in <out>/parts.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import zlib
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg.training import prompt, records as R, sampler, window as W        # noqa: E402

TRAIN_AREAS = ["paris_marais", "paris_batignolles", "paris_montparnasse", "munich_maxvorstadt", "munich_haidhausen", "munich_schwabing"]
TEST_AREAS = ["paris_center", "munich_center"]
SPLITS = {"sft": (6000, TRAIN_AREAS), "rl": (2000, TRAIN_AREAS), "val": (500, TRAIN_AREAS),
          "test": (1000, TEST_AREAS), "test_heldout": (300, TEST_AREAS), "test_long": (200, TEST_AREAS)}
PER_WINDOW = {"sft": 8, "rl": 8, "val": 6, "test": 8, "test_heldout": 4, "test_long": 4}
VAL_SHARE, GAP = 0.15, W.SIZE


def windows_of(M, area: str, n: int) -> list:
    """(kind, centre): every signalised crossing first (they are rare), then the usual mix."""
    seed = zlib.crc32(area.encode())
    rng = random.Random(seed)
    chosen: list = []

    def far(c) -> bool:
        return all(max(abs(c[0] - o[0]), abs(c[1] - o[1])) >= 20.0 for _, o in chosen)

    signals = [c.pos for c in M.crossings if c.control == "signals"]
    rng.shuffle(signals)
    for a in signals:
        c = (a[0] + rng.uniform(-5, 5), a[1] + rng.uniform(-5, 5))
        if len(chosen) < n // 3 and far(c) and W.walkable_share(M, c) >= 0.05:
            chosen.append(("signal", c))
    for kind, c in W.select(M, n * 2, seed + 1):
        if len(chosen) < n and far(c):
            chosen.append((kind, c))
    rng.shuffle(chosen)
    return chosen


def split_windows(M, area: str, n: int) -> dict:
    """{split: [(window id, kind, centre)]} for one area; windows of different splits never share ground between train and val."""
    # centres are stored with 3 decimals; build from exactly the stored value so a window can be rebuilt bit for bit
    chosen = [(k, (round(c[0], 3), round(c[1], 3))) for k, c in windows_of(M, area, n)]
    named = [(f"{area}_{i:04d}", k, c) for i, (k, c) in enumerate(chosen)]
    if area in TEST_AREAS:
        out = {"test": [], "test_heldout": [], "test_long": []}
        for i, x in enumerate(named):
            out[("test", "test", "test_heldout", "test", "test_long")[i % 5]].append(x)
        return out
    xs = sorted(c[0] for _, _, c in named)
    cut = xs[int(len(xs) * (1 - VAL_SHARE))]
    val = [x for x in named if x[2][0] >= cut]
    train = [x for x in named if x[2][0] <= cut - GAP]
    return {"sft": [x for i, x in enumerate(train) if i % 4], "rl": [x for i, x in enumerate(train) if not i % 4], "val": val}


def one_part(job: tuple) -> dict:
    split, area, quota, n_windows, out_dir = job
    out = Path(out_dir) / "parts" / f"{split}__{area}.jsonl"
    meta = out.with_suffix(".json")
    if out.exists() and meta.exists():
        return json.loads(meta.read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    M = sampler.load_tool_server(ROOT / "train" / "maps_city" / f"{area}.osm").model
    mine = split_windows(M, area, n_windows)[split]
    held = split == "test_heldout"
    balance = R.Balance(((4, 0.6), (5, 0.4))) if split == "test_long" else R.Balance()
    rng = random.Random(f"{split}:{area}")
    why: Counter = Counter()
    rows, used, seen = [], [], set()
    built: list = []                                    # (window, map text, kind, centre)
    queue = list(mine)

    def add(w, text, wkind, centre) -> bool:
        got = R.make(w, balance, rng, held, why)
        if got is None or (w.id, got["request"]) in seen:
            return False
        seen.add((w.id, got["request"]))
        rows.append({"id": f"{split}-{area}-{len(rows):05d}", "split": split, "city": area.split("_")[0], "area": area, "window": w.id,
                     "centre": [round(v, 3) for v in centre], "window_kind": wkind, "kind": got["kind"], "record": got["record"],
                     "request": got["request"], "system": prompt.system_prompt(), "user": prompt.user_prompt(text, got["request"]),
                     "reply": got["reply"], "walk": got["facts"]})
        return True

    # first pass: up to PER_WINDOW records per window; further passes on the same windows if the area is too small
    while queue and len(rows) < quota:
        wid, wkind, centre = queue.pop(0)
        window = W.build(M, centre)
        local = W.localise(M, window, centre)
        w = R.Window(wid, window, local)
        text = W.to_text(window)
        before = len(rows)
        for _ in range(PER_WINDOW[split]):
            if len(rows) >= quota or (not add(w, text, wkind, centre) and len(rows) == before):
                break
        if len(rows) > before:
            used.append({"window": wid, "split": split, "area": area, "kind": wkind, "centre": [round(v, 3) for v in centre]})
            built.append((w, text, wkind, centre))
    extra = 0
    while len(rows) < quota and built and extra < quota * 4:
        add(*built[extra % len(built)])
        extra += 1
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    info = {"split": split, "area": area, "quota": quota, "records": len(rows), "windows": used, "windows_available": len(mine),
            "second_pass_attempts": extra, "rejected": why}
    meta.write_text(json.dumps(info), encoding="utf-8")
    return info


def stats(out: Path, infos: list) -> str:
    md = ["# Paris / Munich L1 dataset", ""]
    md += ["| split | records | windows | areas |", "|---|---|---|---|"]
    all_rows = {}
    for split in SPLITS:
        rows = [json.loads(l) for i in infos if i["split"] == split
                for l in (out / "parts" / f"{split}__{i['area']}.jsonl").read_text(encoding="utf-8").splitlines()]
        all_rows[split] = rows
        (out / f"{split}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        md.append(f"| {split} | {len(rows)} | {len({r['window'] for r in rows})} | {len({r['area'] for r in rows})} |")
    rows = [r for v in all_rows.values() for r in v]
    md += ["", f"total {len(rows)} records; distinct types {len({r['kind'] for r in rows})}; "
               f"distinct requests {len({r['request'] for r in rows})}"]

    def table(title, counter):
        md.extend(["", f"| {title} | records |", "|---|---|"] + [f"| {k} | {v} |" for k, v in counter.most_common()])

    table("city", Counter(r["city"] for r in rows))
    table("steps per record", Counter(len(r["record"]["steps"]) for r in rows))
    table("step kind (count of uses)", Counter(s["kind"] for r in rows for s in r["record"]["steps"]))
    table("rule (count of uses)", Counter(x["kind"] for r in rows for x in r["record"]["rules"]))
    table("order", Counter(r["record"]["order"] for r in rows))
    table("vehicle", Counter(r["kind"].rsplit("|", 1)[1] for r in rows))
    md += ["", "| rule | records with it | walks that ignore it fail |", "|---|---|---|"]
    for k in R.RULES:
        have = [r for r in rows if any(x["kind"] == k for x in r["record"]["rules"])]
        md.append(f"| {k} | {len(have)} | {sum(k in r['walk']['matters'] for r in have)} |")
    why: Counter = Counter()
    for i in infos:
        why.update(i["rejected"])
    md += ["", f"rejected candidates: {sum(why.values())}", "", "| rejection reason | count |", "|---|---|"]
    md += [f"| {k.replace('|', '/')} | {v} |" for k, v in why.most_common(30)]
    (out / "windows.json").write_text(json.dumps([w for i in infos for w in i["windows"]], indent=1), encoding="utf-8")
    text = "\n".join(md) + "\n"
    (out / "STATS.md").write_text(text, encoding="utf-8")
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--scale", type=float, default=1.0, help="fraction of every split size")
    ap.add_argument("--out", default=str(ROOT / "train" / "data_city"))
    ap.add_argument("--allow-missing", action="store_true", help="check runs only: leave out areas whose map is absent")
    a = ap.parse_args()
    # windows per area: enough for the quota at PER_WINDOW records each, with a quarter in reserve
    need = {}
    for area in TRAIN_AREAS:
        need[area] = math.ceil((8000 / 6 / 8) * 1.25 / (1 - VAL_SHARE - 0.08) * max(a.scale, 0.02))
    for area in TEST_AREAS:
        need[area] = math.ceil((1500 / 2 / 6) * 1.4 * max(a.scale, 0.04))
    missing = [x for x in TRAIN_AREAS + TEST_AREAS if not (ROOT / "train" / "maps_city" / f"{x}.osm").exists()]
    if missing and not a.allow_missing:
        raise SystemExit(f"missing maps {missing}: run scripts/fetch_city_maps.py")
    jobs = []
    for split, (total, areas) in SPLITS.items():
        areas = [x for x in areas if x not in missing]
        jobs += [(split, area, math.ceil(total * a.scale / len(areas)), need[area], a.out) for area in areas]
    t0 = time.time()
    infos = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futures = [ex.submit(one_part, j) for j in jobs]
        for f in as_completed(futures):
            i = f.result()
            infos.append(i)
            print(f"{i['split']}/{i['area']}: {i['records']}/{i['quota']} records, {len(i['windows'])}/{i['windows_available']} windows, "
                  f"{sum(i['rejected'].values())} rejected ({(time.time() - t0) / 60:.1f} min)", flush=True)
    infos.sort(key=lambda i: (list(SPLITS).index(i["split"]), i["area"]))
    print(stats(Path(a.out), infos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
