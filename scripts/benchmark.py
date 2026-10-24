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
import os
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

FAILED = {"accepted": False, "first_try": False, "attempts": 0, "spec_attempts": 0, "axes": None, "axes_exact": False, "recall": 0.0,
          "atoms_ok": False, "adherent": False, "nominal_ok": False, "n_tasks": 0, "n_defs": 0, "formula_nodes": 0, "warnings": 0}
REAL_OSM = ROOT / ".usg_cache" / "osm_5d4fc3ebb4ec.osm"


def load_map(kind: str, level: int) -> ToolServer:
    t = ToolServer(level=level)
    cached = ROOT / "eval" / "maps" / f"{ {'sophia': 'sophia_antipolis'}.get(kind, kind) }.osm"
    if cached.exists():                                       # any area fetched by scripts/fetch_maps.py
        text = cached.read_text(encoding="utf-8")
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


def run_one(llm: LLMClient, entry: dict, level: int, max_steps: int, vision: bool = False, save_specs: bool = False) -> dict:
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
    elif save_specs:                                         # accepted scenarios feed scripts/make_dataset.py --runs
        rec["spec"], rec["xosc"], rec["margins"] = t.result["spec"], t.result["xosc"], t.result.get("margins")
    return rec


def run_template(llm: LLMClient, entry: dict, max_tokens: int = 4000) -> dict:
    """Condition T0, the "bare prompt template": ONE model call with the same context the L0 agent gets (map overview, inventory, the
    reference script of the guessed type) and the request, no tools, no repair loop. The reply is validated once. This is what a user gets by
    pasting the template into a chat model; the difference to L0 is the value of the framework's tools and validator feedback."""
    import re
    from usg import grounding
    t = load_map(entry["map"], 0)
    t.prompt = entry["text"]
    t0 = time.time()
    guess = classify(entry["text"])[0]
    overview = t.call("get_map_overview")
    template = t.call("get_scenario_template", {"type": guess})
    msg = (f"You write Python scripts for a pedestrian scenario library.\nRequest: {entry['text']}\n\n"
           f"Map overview: {json.dumps({k: v for k, v in overview.items() if k != 'ok'})[:1800]}\n{grounding.inventory_text(t.q)}\n\n"
           f"Most likely scenario type: {guess}. Here is its working reference script (it adapts to this map by itself):\n"
           f"```python\n{template.get('script', '')}\n```\n"
           "Adapt it to the request (texts, speeds, timeouts, which crossing/landmark). Reply with ONE complete python script in a ```python block and nothing else.")
    reason, code = "", ""
    try:
        reply = llm.chat([{"role": "user", "content": msg}], max_tokens=max_tokens)
        m = re.search(r"```(?:python)?\s*\n(.*?)```", reply, re.S)
        code = (m.group(1) if m else reply).strip()
        if code:
            t.call("submit_script", {"code": code})
        else:
            reason = "empty reply"
    except LLMError as e:
        reason = f"model error: {e}"
    rec = {"id": entry["id"], "type": entry["type"], "map": entry["map"], "level": "T0", "guess": guess, "steps": 1,
           "seconds": round(time.time() - t0, 1), "reason": reason, "trace": []}
    rec.update(score(entry, t, 0))
    if not rec["accepted"]:
        rec["last_code"] = code
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
    ap.add_argument("--models", nargs="*", default=[None], metavar="HINT",
                    help="LM Studio models to run one after the other (part of the name, e.g. 0.6B 1.7B 4B); default: the preferred one")
    ap.add_argument("--base-url", help="use a hosted / remote OpenAI-compatible endpoint instead of LM Studio (e.g. Claude or Gemini through their "
                    "OpenAI-compatibility layer, or a vLLM / Ollama server with a larger open model)")
    ap.add_argument("--remote-models", nargs="*", default=[], help="model names to request from --base-url")
    ap.add_argument("--api-key-env", default="API_KEY", help="environment variable that holds the API key for --base-url")
    ap.add_argument("--template", action="store_true", help="also run condition T0, the bare prompt template (one call, no tools, no repair)")
    ap.add_argument("--save-specs", action="store_true", help="store the accepted spec/xosc/margins in every record (for the dataset)")
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
                done.add((r["id"], r["level"], r.get("rep", 0), r.get("model")))

    def emit(rec: dict) -> None:
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"[{rec['level']}] {rec['id']:16s} accepted={rec['accepted']} first_try={rec['first_try']} adherent={rec['adherent']} "
              f"steps={rec['steps']} {rec['seconds']}s {rec['reason']}", flush=True)

    for p in prompts:
        if (p["id"], "baseline", 0, None) not in done:
            rec = baseline(p)
            rec["rep"] = 0
            emit(rec)
    if a.no_llm:
        return 0

    t_all = time.time()

    def play(label: str, llm: LLMClient) -> None:
        for rep in range(a.reps):
            for p in prompts:
                if a.template and (p["id"], "T0", rep, label) not in done:
                    try:
                        rec = run_template(llm, p)
                    except Exception as e:
                        rec = {"id": p["id"], "type": p["type"], "map": p["map"], "level": "T0", "steps": 1, "seconds": 0.0,
                               "reason": f"{type(e).__name__}: {e}", "trace": [], **FAILED}
                    rec["rep"], rec["model"] = rep, label
                    emit(rec)
                for level in a.levels:
                    lv = f"{level}v" if a.vision else level
                    if (p["id"], lv, rep, label) in done:
                        continue
                    try:
                        rec = run_one(llm, p, level, a.max_steps, a.vision, a.save_specs)
                    except Exception as e:                                   # keep the benchmark going whatever one run does
                        rec = {"id": p["id"], "type": p["type"], "map": p["map"], "level": lv, "steps": 0, "seconds": 0.0,
                               "reason": f"{type(e).__name__}: {e}", "trace": [], **FAILED}
                    rec["rep"], rec["model"] = rep, label
                    emit(rec)

    if a.base_url:                                            # hosted / remote models through an OpenAI-compatible endpoint
        key = os.environ.get(a.api_key_env, "")
        if not key:                                           # local vLLM / Ollama servers need none; hosted APIs will answer 401
            print(f"note: no API key in ${a.api_key_env}; sending none", file=sys.stderr)
            key = "not-needed"
        for name in a.remote_models:
            print(f"remote model: {name} at {a.base_url}", flush=True)
            play(f"api:{name}", LLMClient(base_url=a.base_url, model=name, api_key=key, temperature=a.temperature,
                                          context_tokens=a.ctx, local_extras=False))
    else:
        for hint in a.models:
            model = localllm.preferred(localllm.list_models(), hint)
            if model is None:
                print(f"no downloaded model found in LM Studio for {hint or 'the default'}", file=sys.stderr)
                return 2
            print(f"model: {model.label}; starting the local server ...", flush=True)
            print(localllm.SERVER.start(model, "auto", a.ctx, vision=a.vision), flush=True)
            try:
                play(model.label, LLMClient(base_url=localllm.SERVER.base_url, model="local", temperature=a.temperature, context_tokens=a.ctx))
            finally:
                localllm.SERVER.stop()
    print(f"finished in {(time.time() - t_all) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
