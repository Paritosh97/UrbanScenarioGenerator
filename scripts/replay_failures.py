"""Replay recorded benchmark failures through the deterministic safety nets (usg.assist) - offline, no language model needed.

    python scripts/replay_failures.py ../paper/results/sophia_l2.jsonl --prompts eval/prompts_sophia.json --map sophia_antipolis [--esmini DIR]

For every run that the model did not finish (not accepted), the recorded last specification (if any) is resubmitted and the harness's rescue is run:
first the world script is written from the accepted specification ("assisted"), then, if that is not possible, the reference script of the most likely
scenario type is submitted ("fallback"). The table shows how many failed runs end in a valid scenario by which tier, and, with --esmini, how many of those
load and run in esmini. It measures the safety net, not the model: the runs that the model finished on its own are not touched.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import importlib.util                                             # noqa: E402

from usg import esmini as esm                                     # noqa: E402
from usg.agent.loop import _rescue                                # noqa: E402
from usg.tools import ToolServer                                  # noqa: E402


def _load_benchmark():
    spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts" / "benchmark.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmark"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--map", required=True, help="name of eval/maps/<name>.osm")
    ap.add_argument("--level", type=int, default=2)
    ap.add_argument("--esmini", help="esmini bin folder: also require that every rescued scenario loads and runs in it")
    ap.add_argument("--assist", default="fallback", choices=["world", "fallback"])
    ap.add_argument("--out", default=str(ROOT.parent / "paper" / "results" / "replay_failures.md"))
    a = ap.parse_args()

    prompts = {p["id"]: p for p in json.loads(Path(a.prompts).read_text(encoding="utf-8"))["prompts"]}
    osm_text = (ROOT / "eval" / "maps" / f"{a.map}.osm").read_text(encoding="utf-8")
    exe = esm.find(a.esmini) if a.esmini else None
    rows = [json.loads(line) for line in Path(a.runs).read_text(encoding="utf-8").splitlines() if line.strip()]
    failed = [r for r in rows if r["level"] == a.level and not r["accepted"]]
    bench = _load_benchmark()
    tiers, reasons, by_type, esm_fail, adherent = Counter(), Counter(), {}, [], Counter()
    t0 = time.time()
    for r in failed:
        t = ToolServer(level=a.level)
        t.load_osm(osm_text)
        t.assist = a.assist
        t.esmini = exe
        t.prompt = prompts[r["id"]]["text"]
        if r.get("last_spec"):
            t.call("submit_spec", {"spec": r["last_spec"]})
        ev = list(_rescue(t, 0, r["reason"]))
        done = next((e for e in ev if e["kind"] == "done"), None)
        tier = (done or {}).get("tier", "none")
        tiers[tier] += 1
        if done:
            sc = bench.score(prompts[r["id"]], t, a.level)
            adherent[tier] += bool(sc["adherent"])
        reasons[(r["reason"][:40], tier)] += 1
        by_type.setdefault(r["type"], Counter())[tier] += 1
        if tier == "none" and exe:
            esm_fail.append(r["id"])
        print(f"{r['id']:18s} {r['reason'][:34]:34s} -> {tier}", flush=True)
    n = len(failed)
    lines = ["# Replay of the recorded failures through the safety nets", "",
             f"{n} runs of `{Path(a.runs).name}` (level {a.level}, map {a.map}) that the model did not finish. Safety nets: `{a.assist}`"
             + (f"; every rescued scenario must also load and run in esmini" if exe else "") + ".", "",
             "| outcome | runs |", "|---|---|"]
    lines[-2:] = ["| outcome | runs | adherent to the request |", "|---|---|---|"]
    for k in ("assisted", "fallback", "none"):
        lines.append(f"| {k} | {tiers.get(k, 0)} | {adherent.get(k, 0) if k != 'none' else '-'} |")
    lines += ["", f"Valid output after the nets: {n - tiers.get('none', 0)}/{n}. The model alone finished {sum(r['accepted'] for r in rows if r['level'] == a.level)}"
              f"/{sum(1 for r in rows if r['level'] == a.level)} runs of this level; the runs finished by `assisted` or `fallback` are NOT model successes and are reported separately.",
              "", "| type | assisted | fallback | none |", "|---|---|---|---|"]
    for ty, c in sorted(by_type.items()):
        lines.append(f"| {ty} | {c.get('assisted', 0)} | {c.get('fallback', 0)} | {c.get('none', 0)} |")
    lines += ["", f"({time.time() - t0:.0f} s)", ""]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
