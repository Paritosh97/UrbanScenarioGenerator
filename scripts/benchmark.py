"""Quantitative evaluation of the generator (RQ2 and RQ3).

For every prompt in ``eval/prompts.json`` and every pipeline level the local model generates a scenario; each run is
scored automatically (no human judgement):

* ``accepted``   the map-aware validator accepted the final scenario (validity)
* ``first_try``  it was accepted at the first specification/script submission (= "no repair loop")
* ``axes_exact`` the constraint axes of the generated scenario equal the axes the prompt asks for (adherence)
* ``recall``     fraction of the requested axes that are present
* ``atoms_ok``   required specification operators (e.g. look_at) occur, for prompts the task helpers cannot express
* ``nominal_ok`` a nominal walker satisfies every task formula on the map (satisfiability margin >= 0)

A keyword baseline (classify the prompt, run the reference script of that type, no model) is scored the same way.
Results are appended to a JSONL file, so an interrupted run resumes where it stopped.

    python scripts/benchmark.py --levels 0 1 2 --reps 1 --out ../paper/results/benchmark.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg import localllm, synth                                   # noqa: E402
from usg.agent.loop import run_agent                              # noqa: E402
from usg.llm import LLMClient, LLMError                           # noqa: E402
from usg.scenario_types import AXES, AXIS_DEFAULTS, ARCHETYPES, axes_of, classify   # noqa: E402
from usg.spec import formula as F                                 # noqa: E402
from usg.tools import ToolServer                                  # noqa: E402

REAL_OSM = ROOT / ".usg_cache" / "osm_5d4fc3ebb4ec.osm"


def load_map(kind: str, level: int) -> ToolServer:
    t = ToolServer(level=level)
    if kind == "sophia":
        text = (ROOT / "eval" / "maps" / "sophia_antipolis.osm").read_text(encoding="utf-8")
    else:
        text = REAL_OSM.read_text(encoding="utf-8") if kind == "real" else synth.synthetic_osm()
    t.load_osm(text)
    return t


def score(entry: dict, t: ToolServer, level: int) -> dict:
    """Automatic metrics of one finished run."""
    r = t.result
    out = {"accepted": r is not None, "attempts": t.attempts, "spec_attempts": t.spec_attempts}
    out["first_try"] = bool(r) and t.attempts == 1 and t.spec_attempts <= (0 if level == 0 else 1)
    if not r:
        out.update(axes=None, axes_exact=False, recall=0.0, atoms_ok=False, adherent=False, nominal_ok=False,
                   n_tasks=0, n_defs=0, formula_nodes=0, warnings=0)
        return out
    spec = r["spec"]
    ax = axes_of(spec, t.model)
    exp = entry["expect"].get("axes", {})
    exact = all((ax[a] == exp[a]) if a in exp else (a == "surface" or ax[a] == AXIS_DEFAULTS[a]) for a in AXES)
    recall = sum(ax[a] == v for a, v in exp.items()) / max(1, len(exp))
    ops = {a["op"] for tk in spec["tasks"] for fm in [tk["goal"]] + list(tk["safety"]) for a in F.atoms_in(fm)}
    want = entry["expect"].get("atoms", [])
    atoms_ok = (not want) or any(o in ops for o in want)
    mg = r.get("margins") or {}
    nominal_ok = bool(mg) and all(v["ok"] for v in mg.values())
    doc = r.get("spec_doc") or {}
    nodes = sum(F.measure(fm)[0] for tk in spec["tasks"] for fm in [tk["goal"]] + list(tk["safety"]))
    out.update(axes=ax, axes_exact=exact, recall=round(recall, 3), atoms_ok=atoms_ok, adherent=exact and atoms_ok,
               nominal_ok=nominal_ok, n_tasks=len(spec["tasks"]), n_defs=len(doc.get("defs") or {}), formula_nodes=nodes,
               warnings=sum(1 for i in r["issues"] if i["severity"] == "warning"), ops=sorted(ops))
    return out


def run_one(llm: LLMClient, entry: dict, level: int, max_steps: int, vision: bool = False) -> dict:
    t = load_map(entry["map"], level)
    t.vision = vision
    t0 = time.time()
    steps, reason, trace, feedback = 0, "", [], []
    try:
        for ev in run_agent(llm, t, entry["text"], max_steps):
            if ev["kind"] in ("done", "failed"):
                steps, reason = ev.get("steps", 0), ev.get("reason", "")
            elif ev["kind"] in ("tool", "result"):
                trace.append((ev["kind"][0], ev["name"], ev.get("ok", True)))
                if ev["kind"] == "result" and ev["name"] in ("submit_spec", "submit_script") and not ev.get("ok"):
                    feedback.append(f"{ev['name']}: {ev.get('summary', '')[:700]}")
    except LLMError as e:
        reason = f"model error: {e}"
    rec = {"id": entry["id"], "type": entry["type"], "map": entry["map"], "level": f"{level}v" if vision else level, "steps": steps,
           "seconds": round(time.time() - t0, 1), "reason": reason, "trace": trace[-24:], "feedback": feedback[-4:]}
    rec.update(score(entry, t, level))
    if not rec["accepted"]:                                  # keep what the model last submitted, for diagnosis
        rec["last_spec"], rec["last_code"] = t.last_spec, t.last_code
    return rec


def baseline(entry: dict) -> dict:
    """Keyword classification + the reference script of the guessed type; no model."""
    t = load_map(entry["map"], 0)
    guess = classify(entry["text"])[0]
    t0 = time.time()
    t.call("submit_script", {"code": ARCHETYPES[guess]["template"]})
    rec = {"id": entry["id"], "type": entry["type"], "map": entry["map"], "level": "baseline", "guess": guess, "steps": 0,
           "seconds": round(time.time() - t0, 1), "reason": "", "trace": []}
    rec.update(score(entry, t, 0))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default=str(ROOT / "eval" / "prompts.json"))
    ap.add_argument("--out", default=str(ROOT.parent / "paper" / "results" / "benchmark.jsonl"))
    ap.add_argument("--levels", type=int, nargs="*", default=[0, 1, 2])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="only the first N prompts (smoke test)")
    ap.add_argument("--only", nargs="*", default=[], help="prompt ids to run")
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--max-steps", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--no-llm", action="store_true", help="only the keyword baseline")
    ap.add_argument("--vision", action="store_true", help="vision ablation: attach an annotated top-down map image (needs the model's mmproj); levels are recorded as 0v/1v/2v")
    a = ap.parse_args()

    prompts = json.loads(Path(a.prompts).read_text(encoding="utf-8"))["prompts"]
    if a.only:
        prompts = [p for p in prompts if p["id"] in a.only]
    if a.limit:
        prompts = prompts[:a.limit]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["id"], r["level"], r.get("rep", 0)))

    def emit(rec: dict) -> None:
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"[{rec['level']}] {rec['id']:16s} accepted={rec['accepted']} first_try={rec['first_try']} adherent={rec['adherent']} "
              f"steps={rec['steps']} {rec['seconds']}s {rec['reason']}", flush=True)

    for p in prompts:
        if (p["id"], "baseline", 0) not in done:
            rec = baseline(p)
            rec["rep"] = 0
            emit(rec)
    if a.no_llm:
        return 0

    model = localllm.preferred(localllm.list_models(), None)
    if model is None:
        print("no downloaded model found in LM Studio", file=sys.stderr)
        return 2
    print(f"model: {model.label}; starting the local server ...", flush=True)
    print(localllm.SERVER.start(model, "auto", a.ctx, vision=a.vision), flush=True)
    llm = LLMClient(base_url=localllm.SERVER.base_url, model="local", temperature=a.temperature, context_tokens=a.ctx)
    t_all = time.time()
    try:
        for rep in range(a.reps):
            for p in prompts:
                for level in a.levels:
                    label = f"{level}v" if a.vision else level
                    if (p["id"], label, rep) in done:
                        continue
                    try:
                        rec = run_one(llm, p, level, a.max_steps, a.vision)
                    except Exception as e:                                       # keep the benchmark going whatever one run does
                        rec = {"id": p["id"], "type": p["type"], "map": p["map"], "level": label, "steps": 0, "seconds": 0.0,
                               "reason": f"{type(e).__name__}: {e}", "trace": [], "accepted": False, "first_try": False,
                               "attempts": 0, "spec_attempts": 0, "axes": None, "axes_exact": False, "recall": 0.0,
                               "atoms_ok": False, "adherent": False, "nominal_ok": False, "n_tasks": 0, "n_defs": 0,
                               "formula_nodes": 0, "warnings": 0}
                    rec["rep"] = rep
                    emit(rec)
    finally:
        localllm.SERVER.stop()
        print(f"finished in {(time.time() - t_all) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
