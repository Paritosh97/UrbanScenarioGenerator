r"""L2 results per scenario type on the Sophia Antipolis map -> LaTeX table + appendix of prompts.

usage: python scripts/sophia_table.py [results.jsonl] [prompts.json] [out_dir]
Writes <out_dir>/table_l2.tex (a longtable, \input into the paper) and <out_dir>/appendix_prompts.tex.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from summarize_benchmark import wilson                                              # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
res = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "paper" / "results" / "sophia_l2.jsonl")
prm = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT / "eval" / "prompts_sophia.json")
out = Path(sys.argv[3] if len(sys.argv) > 3 else ROOT.parent / "paper" / "results")

BS = "\\"
TYPES = [
    ("ptp_env", "Reach a landmark (bus stop, bench, waste basket) over walkable ground"),
    ("ptp_road", "Reach a spot on the carriageway"),
    ("cpath", "Reach a goal while staying inside a corridor (path or sidewalk)"),
    ("env_con", "Reach a goal without touching static obstacles (parked cars)"),
    ("dyn_nav", "Cross while keeping clear of a moving vehicle"),
    ("dep_comp", "Several goals that must be reached in a given order"),
    ("indep_comp", "Several goals that may be reached in any order"),
    ("mixed", "Combined constraints: signal compliance, a moving car, looking at it"),
]


def tt(s: str) -> str:
    return BS + "texttt{" + s.replace("_", BS + "_") + "}"


def frac(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}{BS}%; {100 * lo:.0f}--{100 * hi:.0f})"


prompts = json.loads(prm.read_text(encoding="utf-8"))["prompts"]
runs = [json.loads(line) for line in res.read_text(encoding="utf-8").splitlines() if line.strip()]
runs = [r for r in runs if str(r["level"]) == "2"]
by = defaultdict(list)
for r in runs:
    by[r["type"]].append(r)

head = f"Scenario type & Task description & Quantitative metric & Result {BS}{BS}"
L = [
    BS + "begin{longtable}{@{}p{1.7cm}p{2.9cm}p{4.4cm}p{3.1cm}@{}}",
    BS + "caption{Performance of the L2 pipeline per scenario type on the Sophia Antipolis map. Result: count (percentage; 95" + BS + "% Wilson interval) over all runs of that type.}"
    + BS + "label{tab:l2_results}" + BS + BS,
    BS + "toprule", head, BS + "midrule", BS + "endfirsthead", BS + "toprule", head, BS + "midrule", BS + "endhead",
]
kinds = [k for k, _ in TYPES if by.get(k)]
for i, (key, desc) in enumerate((k, d) for k, d in TYPES if by.get(k)):
    rs = by[key]
    n = len(rs)
    metrics = [
        ("Accepted (validator passes the final scenario)", frac(sum(r["accepted"] for r in rs), n)),
        ("First try (accepted with no repair loop)", frac(sum(r["first_try"] for r in rs), n)),
        ("Adherent (constraint axes and operators match the request)", frac(sum(r["adherent"] for r in rs), n)),
        ("Solvable (the nominal walker satisfies all tasks)", frac(sum(r["nominal_ok"] for r in rs), n)),
        ("Script submissions per run (mean)", f"{sum(r['attempts'] for r in rs) / n:.2f}"),
        ("Model steps per run (mean)", f"{sum(r['steps'] for r in rs) / n:.1f}"),
        ("Wall-clock per run, s (mean)", f"{sum(r['seconds'] for r in rs) / n:.0f}"),
    ]
    for j, (mt, val) in enumerate(metrics):
        c1 = f"{tt(key)} ({n} run{'s' if n != 1 else ''})" if j == 0 else ""
        c2 = desc if j == 0 else ""
        L.append(f"{c1} & {c2} & {mt} & {val} {BS}{BS}")
    if i < len(kinds) - 1:
        L.append(BS + "midrule")
L += [BS + "bottomrule", BS + "end{longtable}"]
(out / "table_l2.tex").write_text("\n".join(L) + "\n", encoding="utf-8")

A = [BS + "begin{longtable}{@{}p{3.5cm}p{2.5cm}p{6.2cm}@{}}",
     BS + "caption{Evaluation prompts (Sophia Antipolis map, all requested object types exist on it).}" + BS + "label{tab:prompts}" + BS + BS,
     BS + "toprule", f"Id & Type & Prompt {BS}{BS}", BS + "midrule", BS + "endhead"]
for p in prompts:
    A.append(f"{tt(p['id'])} & {tt(p['type'])} & {p['text'].replace('&', BS + '&')} {BS}{BS}")
A += [BS + "bottomrule", BS + "end{longtable}"]
(out / "appendix_prompts.tex").write_text("\n".join(A) + "\n", encoding="utf-8")
print(f"{len(runs)} L2 runs; wrote table_l2.tex ({len(kinds)} types) and appendix_prompts.tex")
