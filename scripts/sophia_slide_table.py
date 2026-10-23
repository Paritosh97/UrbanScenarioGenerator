r"""Compact landscape version of the L2 per-type table (for a slide): one row per scenario type.

usage: python scripts/sophia_slide_table.py [results.jsonl] [out_dir]
Writes <out_dir>/table_l2_slide.tex (standalone) and compiles it to table_l2_slide.pdf / .png (needs pdflatex and pdftoppm).
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
res = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "paper" / "results" / "sophia_l2.jsonl")
out = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT.parent / "paper" / "results")
BS = "\\"

TYPES = [
    ("ptp_env", "Reach a landmark over walkable ground"),
    ("ptp_road", "Reach a spot on the carriageway"),
    ("cpath", "Reach a goal inside a corridor"),
    ("env_con", "Reach a goal without touching parked cars"),
    ("dyn_nav", "Cross while keeping clear of a moving car"),
    ("dep_comp", "Several goals in a given order"),
    ("indep_comp", "Several goals in any order"),
    ("mixed", "Signal compliance + moving car + looking"),
]
runs = [json.loads(line) for line in res.read_text(encoding="utf-8").splitlines() if line.strip()]
by = defaultdict(list)
for r in runs:
    if str(r["level"]) == "2":
        by[r["type"]].append(r)


def cell(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.0f}{BS}%)"


head = ["Scenario type", "Task description", "Runs", "Accepted", "First try", "Adherent", "Solvable", "Submissions / run"]
L = [BS + "documentclass[border=10pt,12pt]{standalone}", BS + "usepackage{booktabs,array}", BS + "usepackage[T1]{fontenc}", BS + "usepackage{helvet}",
     BS + "renewcommand{" + BS + "familydefault}{" + BS + "sfdefault}", BS + "begin{document}",
     BS + "renewcommand{" + BS + "arraystretch}{1.35}",
     BS + "begin{tabular}{@{}l l c c c c c c@{}}", BS + "toprule",
     " & ".join(BS + "textbf{" + h + "}" for h in head) + " " + BS + BS, BS + "midrule"]
for key, desc in TYPES:
    rs = by.get(key, [])
    n = len(rs)
    if not n:
        continue
    row = [BS + "texttt{" + key.replace("_", BS + "_") + "}", desc, str(n),
           cell(sum(r["accepted"] for r in rs), n), cell(sum(r["first_try"] for r in rs), n),
           cell(sum(r["adherent"] for r in rs), n), cell(sum(r["nominal_ok"] for r in rs), n),
           f"{sum(r['attempts'] for r in rs) / n:.2f}"]
    L.append(" & ".join(row) + " " + BS + BS)
L += [BS + "bottomrule", BS + "end{tabular}", BS + "end{document}"]
tex = out / "table_l2_slide.tex"
tex.write_text("\n".join(L) + "\n", encoding="utf-8")
subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory", str(out), str(tex)], capture_output=True)
subprocess.run(["pdftoppm", "-r", "250", "-png", "-singlefile", str(out / "table_l2_slide.pdf"), str(out / "table_l2_slide")], check=True)
for ext in ("aux", "log"):
    (out / f"table_l2_slide.{ext}").unlink(missing_ok=True)
print("wrote", out / "table_l2_slide.png")
