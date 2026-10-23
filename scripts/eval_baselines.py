"""Run the reference policies of ``usg.baselines`` on a dataset and report success, return and safety cost per split / type.

    python scripts/eval_baselines.py --dataset dataset --seeds 5 --out ../paper/results/env_baselines.md

``route`` is the scripted closed-loop nominal walker (upper bound), ``straight`` heads for the next goal ignoring the map, ``random`` is the
lower bound. A learned agent should land between ``straight`` and ``route``; the gap shows what the map, the lights and the traffic add.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg.baselines import RandomPolicy, RoutePolicy, StraightPolicy, rollout    # noqa: E402
from usg.dataset import iter_scenarios                                          # noqa: E402


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "dataset"))
    ap.add_argument("--seeds", type=int, default=5, help="random-policy seeds per scenario")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT.parent / "paper" / "results" / "env_baselines.md"))
    a = ap.parse_args()

    runs = defaultdict(list)          # (policy, group) -> [rollout dict]
    t0 = time.time()
    for i, sc in enumerate(iter_scenarios(a.dataset)):
        if a.limit and i >= a.limit:
            break
        env = sc.env()
        for name, make, seeds in (("route", lambda: RoutePolicy(env), [0]), ("straight", lambda: StraightPolicy(env), [0]),
                                  ("random", None, list(range(a.seeds)))):
            for s in seeds:
                pol = RandomPolicy(s) if make is None else make()
                res = rollout(env, pol, seed=s)
                for group in ("all", f"split:{sc.row['split']}", f"type:{sc.row['type']}", f"map:{sc.row['map']}"):
                    runs[(name, group)].append(res)
    lines = ["# Reference policies in the headless environment", "",
             f"{sum(len(v) for k, v in runs.items() if k[1] == 'all' and k[0] == 'route')} scenarios; random policy over {a.seeds} seeds. "
             f"`success` = every task of the scenario completed without breaking a rule (Wilson 95% interval); `cost` = share of episodes "
             f"that broke a safety rule; `return` = mean episode return.", "",
             "| group | policy | episodes | success | cost | return |", "|---|---|---|---|---|---|"]
    for group in sorted({g for _, g in runs}, key=lambda g: (g != "all", g)):
        for name in ("route", "straight", "random"):
            rs = runs.get((name, group), [])
            if not rs:
                continue
            k = sum(r["success"] for r in rs)
            lo, hi = wilson(k, len(rs))
            lines.append(f"| {group} | {name} | {len(rs)} | {100 * k / len(rs):.0f}% [{100 * lo:.0f}, {100 * hi:.0f}] | "
                         f"{100 * sum(r['cost'] > 0 for r in rs) / len(rs):.0f}% | {st.mean(r['return'] for r in rs):.2f} |")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"({time.time() - t0:.0f}s) wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
