"""Scenario datasets for training and benchmarking: build, index, load, summarise.

Layout written by ``build_dataset`` (everything is plain JSON / OpenSCENARIO, nothing needs this package to be read)::

    <root>/index.jsonl                one row per scenario: id, map, type, axes, split, counts, nominal margins, source
    <root>/maps/<map>/scene_map.json  the metric map model (+ map.xodr, the same geometry as OpenDRIVE)
    <root>/scenarios/<id>.spec.json   the specification (entities, signals, tasks with goal/safety formulas)
    <root>/scenarios/<id>.xosc        the OpenSCENARIO file (with the <VRTask>/<Spec> extension)
    <root>/scenarios/<id>.xodr        only if the scenario adds signals on crossings without a light: the map's OpenDRIVE plus those signals

Scenarios come from the seven reference scripts (``usg.scenarios``, varied deterministically by the choice of crossing / landmark) and,
with ``runs=``, from accepted LLM runs saved by ``scripts/benchmark.py --save-specs``. Splits are by MAP: the maps in ``test_maps`` form the
held-out split, so a model trained on ``train`` is tested on streets it has never seen.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from . import osm, xodr
from .env import PedestrianTaskEnv
from .mapmodel import MapModel
from .sandbox import run_script
from .scenario_types import ARCHETYPES, axes_of


# ------------------------------------------------------------------ deterministic variants of the reference scripts
def vary(code: str, sid: str, i: int) -> str:
    """Variant ``i`` of a reference script: the same task with another crossing / landmark / pair of landmarks (i = 0 is the original)."""
    if i == 0:
        return code
    if sid in ("cpath", "ptp_road"):
        return code.replace("cr = MAP.crossings()[0]", f"cr = MAP.crossings()[{i} % len(MAP.crossings())]")
    if sid in ("dep_comp", "dyn_nav", "env_con"):
        return re.sub(r"(?m)^(cr = sorted\(.*\))\[0\]", rf"\1[{i} % len(crossings)]", code)
    if sid == "ptp_env":
        return code.replace("stop = landmarks[0]", f"stop = landmarks[{i} % len(landmarks)]")
    if sid == "indep_comp":
        return code.replace("a_prop, b_prop = items[0], items[-1]",
                            f"a_prop, b_prop = items[{i} % len(items)], items[(len(items) - 1 - {i}) % len(items)]")
    return code


# ------------------------------------------------------------------ harder reference scenarios (signals, look_at, traffic)
# The seven reference scripts use the task helpers, which cannot express traffic lights or gaze rules. These three are written as
# SPECIFICATIONS (stage A) plus a world script (stage B), the way the L1/L2 pipelines produce them, built from the map's own ids.
HARD_TYPES = ("signal_cross", "look_cross", "signal_traffic")
_TIMINGS = [(12, 18), (15, 20), (10, 25), (20, 15)]          # (green, red) seconds
_SPEEDS = [8.0, 10.0, 6.0, 9.0]                              # car speed m/s


def _call(name: str, **args) -> dict:
    return {"op": "call", "name": name, "args": args}


def hard_references(model: MapModel, i: int) -> list[tuple[str, dict, str]]:
    """Variant ``i`` of the harder reference scenarios as (type, specification document, world script); only those the map allows."""
    from .dsl import MapQuery
    q = MapQuery(model)
    out: list[tuple[str, dict, str]] = []
    green, red = _TIMINGS[i % len(_TIMINGS)]
    speed, angle = _SPEEDS[i % len(_SPEEDS)], (35 if i % 2 == 0 else 45)
    signalised = [c for c in q.crossings(control="signals")]
    anycross = q.crossings()

    def crossing_zones(cid):
        return ({"kind": "crossing_side", "id": cid, "side": "start", "r": 3}, {"kind": "crossing_side", "id": cid, "side": "end", "r": 2},
                {"kind": "crossing", "id": cid})

    def car_lines(cid, road, s_, handle: str, define: bool = True) -> str:
        return ((f"road, s = {road!r}, {s_!r}\n" if define else "") + f"length = MAP.road(road)['length']\n"
                f"route = MAP.drive_route(road, max(0.0, s - 30.0), min(length, s + 30.0), 'forward')\n"
                f"scenario.vehicle('Car1', route[0], route[1:], speed={speed}, model='car_white', start_when=when_task_starts({handle}))\n")

    if signalised:
        cr = signalised[i % len(signalised)]
        cid = cr["id"]
        o = q._m.get(cid)
        sig = o.signal_id or f"{cid}_ped"
        near, far, box = crossing_zones(cid)
        goal = {"op": "then", "args": [_call("wait_for_green", zone=near, signal=sig), _call("cross", far_zone=far)]}
        head = ("from usg.dsl import *\n"
                f"scenario = ScenarioBuilder('{{n}}', MAP, scenario_type='custom', description='{{d}}')\n"
                f"scenario.user(MAP.crossing_side({cid!r}, 'start', inset=2.0))\n"
                f"scenario.signal_cycle({cid!r}, green={green}, red={red}, initial='red')\n")
        doc = {"tasks": [{"name": "cross_on_green", "instruction": "Wait for the green light, then cross.", "goal": goal,
                          "safety": [_call("obey_signal", zone=box, signal=sig)],
                          "timeout": {"initial": 60 + red, "baseline": 100 + red + green}}]}
        out.append(("signal_cross", doc, head.format(n="signal_cross", d="Wait for green, then cross.") + "scenario.apply_spec(SPEC)\n"))
        doc2 = {"tasks": [{"name": "cross_on_green", "instruction": "Wait for green, then cross; keep clear of the car.", "goal": goal,
                           "safety": [_call("obey_signal", zone=box, signal=sig), _call("collision_free", entity="Car1", r=0.3)],
                           "timeout": {"initial": 70 + red, "baseline": 110 + red + green}}]}
        out.append(("signal_traffic", doc2, head.format(n="signal_traffic", d="Cross on green with a car around.")
                    + "handles = scenario.apply_spec(SPEC)\n" + car_lines(cid, cr["road"], cr["road_s"], "handles[0]")))
    if anycross:
        cr = sorted(anycross, key=lambda c: (q.road(c["road"])["oneway"], -q.road(c["road"])["lanes"], -q.road(c["road"])["length"]))[i % len(anycross)]
        cid = cr["id"]
        near, far, box = crossing_zones(cid)
        doc = {"tasks": [
            {"name": "check_traffic", "instruction": "Look at the approaching car.", "goal": _call("look", entity="Car1", angle=angle, seconds=12),
             "timeout": {"initial": 15, "baseline": 25}},
            {"name": "cross_clear", "instruction": "Cross the road and stay clear of the car.", "after": ["check_traffic"],
             "goal": _call("cross", far_zone=far), "safety": [_call("collision_free", entity="Car1", r=0.3)],
             "timeout": {"initial": 60, "baseline": 90}}]}
        code = ("from usg.dsl import *\n"
                f"road, s = {cr['road']!r}, {cr['road_s']!r}\n"
                "scenario = ScenarioBuilder('look_cross', MAP, scenario_type='custom', description='Look at the car, then cross.')\n"
                # the participant waits facing ALONG the kerb, so the car is not in view and has to be looked for when it passes
                f"scenario.user(MAP.crossing_side({cid!r}, 'start', inset=2.0).facing(MAP.along_road(road, s + 20.0)))\n"
                "handles = scenario.apply_spec(SPEC)\n" + car_lines(cid, cr["road"], cr["road_s"], "handles[0]", define=False))
        out.append(("look_cross", doc, code))
    return out


def _digest(spec: dict) -> str:
    return hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]


def scenario_xodr(model: MapModel, spec: dict, path: Path) -> bool:
    """Write a scenario-specific OpenDRIVE file if the scenario adds signals to crossings that have none; True if written."""
    virtual = [(v["signal"], v["crossing"]) for v in spec.get("virtual_signals", [])]
    if virtual:
        xodr.export_xodr(model, path, virtual=virtual)
    return bool(virtual)


def _row(sid: str, name: str, spec: dict, model: MapModel, split: str, source: str, margins: Optional[dict], extra: Optional[dict] = None) -> dict:
    nominal = {str(k): v for k, v in (margins or {}).items()}
    mins = [v["min_safety"] for v in nominal.values() if v.get("min_safety") is not None]
    row = {"id": sid, "map": name, "type": spec.get("scenario_type"), "axes": axes_of(spec, model), "split": split, "source": source,
           "n_tasks": len(spec["tasks"]), "n_entities": len(spec["entities"]) - 1, "n_signals": len(spec["signals"]),
           "n_vehicles": sum(e["role"] == "vehicle" for e in spec["entities"]), "horizon": spec.get("horizon"),
           "nominal_ok": bool(nominal) and all(v["ok"] for v in nominal.values()),
           "nominal_goal_margin": min((v["goal"] for v in nominal.values()), default=None),
           "nominal_safety_margin": min(mins) if mins else None}
    row.update(extra or {})
    return row


def build_dataset(root: str | Path, maps: dict[str, MapModel], *, variants: int = 4, test_maps: tuple[str, ...] = (),
                  runs: Optional[str | Path] = None, hard: bool = True, log=print) -> list[dict]:
    """Write the dataset for ``maps`` (name -> MapModel) and return the index rows."""
    root = Path(root)
    (root / "scenarios").mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    seen: set[tuple] = set()
    for name, model in maps.items():
        mdir = root / "maps" / name
        mdir.mkdir(parents=True, exist_ok=True)
        model.save(mdir / "scene_map.json")
        xodr.export_xodr(model, mdir / "map.xodr")
        split = "test" if name in test_maps else "train"
        for sid, arch in sorted(ARCHETYPES.items()):
            for i in range(variants):
                res = run_script(vary(arch["template"], sid, i), mdir / "scene_map.json")
                if not (res.ok and res.spec):
                    log(f"  skip {name}/{sid}/v{i}: {(res.error or 'rejected')[:80]}")
                    continue
                key = (name, _digest(res.spec))
                if key in seen:                                           # the index wrapped around: same scenario again
                    continue
                seen.add(key)
                uid = f"{name}__{sid}__v{i}"
                (root / "scenarios" / f"{uid}.spec.json").write_text(json.dumps(res.spec), encoding="utf-8")
                (root / "scenarios" / f"{uid}.xosc").write_text(res.xosc, encoding="utf-8")
                scenario_xodr(model, res.spec, root / "scenarios" / f"{uid}.xodr")
                rows.append(_row(uid, name, res.spec, model, split, "reference", res.margins, {"variant": i}))
        for i in range(variants if hard else 0):
            for kind, doc, code in hard_references(model, i):
                res = run_script(code, mdir / "scene_map.json", spec=doc, level=2)
                if not (res.ok and res.spec):
                    log(f"  skip {name}/{kind}/v{i}: {(res.error or 'rejected')[:100]}")
                    continue
                key = (name, _digest(res.spec))
                if key in seen:
                    continue
                seen.add(key)
                uid = f"{name}__{kind}__v{i}"
                (root / "scenarios" / f"{uid}.spec.json").write_text(json.dumps(res.spec), encoding="utf-8")
                (root / "scenarios" / f"{uid}.xosc").write_text(res.xosc, encoding="utf-8")
                scenario_xodr(model, res.spec, root / "scenarios" / f"{uid}.xodr")
                rows.append(_row(uid, name, res.spec, model, split, "reference_spec", res.margins, {"variant": i, "type": kind}))
        log(f"{name}: {sum(r['map'] == name for r in rows)} scenarios ({split})")
    if runs:
        rows += _ingest_runs(root, maps, runs, test_maps, seen, log)
    (root / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (root / "STATS.md").write_text(stats_markdown(rows), encoding="utf-8")
    return rows


def _ingest_runs(root: Path, maps: dict[str, MapModel], runs, test_maps, seen: set, log) -> list[dict]:
    """Accepted LLM runs that carry their spec (benchmark.py --save-specs)."""
    out = []
    for line in Path(runs).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        name = {"sophia": "sophia_antipolis"}.get(r.get("map"), r.get("map"))
        if not (r.get("accepted") and r.get("spec") and name in maps):
            continue
        if (name, _digest(r["spec"])) in seen:
            continue
        seen.add((name, _digest(r["spec"])))
        uid = f"{name}__llm_{r['id']}_L{r['level']}_{r.get('model', 'm')}_r{r.get('rep', 0)}".replace(" ", "")
        (root / "scenarios" / f"{uid}.spec.json").write_text(json.dumps(r["spec"]), encoding="utf-8")
        if r.get("xosc"):
            (root / "scenarios" / f"{uid}.xosc").write_text(r["xosc"], encoding="utf-8")
        scenario_xodr(maps[name], r["spec"], root / "scenarios" / f"{uid}.xodr")
        out.append(_row(uid, name, r["spec"], maps[name], "test" if name in test_maps else "train", "llm", r.get("margins"),
                        {"prompt_id": r["id"], "level": r["level"], "model": r.get("model"), "adherent": r.get("adherent")}))
    log(f"ingested {len(out)} LLM scenarios from {runs}")
    return out


# ------------------------------------------------------------------ loading
@dataclass
class Scenario:
    row: dict
    spec: dict
    model: MapModel

    def env(self, **kw) -> PedestrianTaskEnv:
        return PedestrianTaskEnv(self.spec, self.model, **kw)


def iter_scenarios(root: str | Path, split: Optional[str] = None, maps: Optional[tuple[str, ...]] = None) -> Iterator[Scenario]:
    """Yield the scenarios of a dataset; ``split`` is 'train' or 'test'."""
    root = Path(root)
    cache: dict[str, MapModel] = {}
    for line in (root / "index.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (split and row["split"] != split) or (maps and row["map"] not in maps):
            continue
        if row["map"] not in cache:
            cache[row["map"]] = MapModel.load(root / "maps" / row["map"] / "scene_map.json")
        spec = json.loads((root / "scenarios" / f"{row['id']}.spec.json").read_text(encoding="utf-8"))
        yield Scenario(row, spec, cache[row["map"]])


# ------------------------------------------------------------------ statistics
def stats_markdown(rows: list[dict]) -> str:
    """Coverage / diversity tables for the paper and the dataset card."""
    if not rows:
        return "# Dataset statistics\n\n(empty)\n"
    maps = sorted({r["map"] for r in rows})
    types = sorted({r["type"] for r in rows if r["type"]})
    lines = ["# Dataset statistics", "", f"{len(rows)} scenarios on {len(maps)} maps; "
             f"{sum(r['split'] == 'train' for r in rows)} train / {sum(r['split'] == 'test' for r in rows)} test (split by map).", "",
             "## Scenarios per map and type", "", "| map | split | " + " | ".join(types) + " | total |", "|---|---|" + "---|" * (len(types) + 1)]
    for m in maps:
        mr = [r for r in rows if r["map"] == m]
        c = Counter(r["type"] for r in mr)
        lines.append(f"| {m} | {mr[0]['split']} | " + " | ".join(str(c.get(t, 0)) for t in types) + f" | {len(mr)} |")
    lines += ["", "## Constraint axes (number of scenarios per value)", "", "| axis | values (count) |", "|---|---|"]
    for ax in sorted({a for r in rows for a in r["axes"]}):
        c = Counter(r["axes"].get(ax) for r in rows)
        lines.append(f"| {ax} | " + ", ".join(f"{k}: {v}" for k, v in sorted(c.items(), key=lambda kv: str(kv[0]))) + " |")

    def mean(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return f"{sum(v) / len(v):.2f}" if v else "-"

    lines += ["", "## Size and difficulty", "",
              f"- tasks per scenario: mean {mean('n_tasks')}; entities: mean {mean('n_entities')}; vehicles: mean {mean('n_vehicles')}; "
              f"signals: mean {mean('n_signals')}",
              f"- horizon (s): mean {mean('horizon')}",
              f"- nominal walker satisfies every task: {sum(bool(r['nominal_ok']) for r in rows)}/{len(rows)}",
              f"- nominal goal margin: mean {mean('nominal_goal_margin')}; nominal safety margin: mean {mean('nominal_safety_margin')}",
              f"- sources: " + ", ".join(f"{k} {v}" for k, v in Counter(r['source'] for r in rows).items()), ""]
    return "\n".join(lines)


def load_maps(paths: dict[str, str | Path]) -> dict[str, MapModel]:
    """name -> MapModel from OSM files (``.osm``) or saved scene maps (``.json``)."""
    out = {}
    for name, p in paths.items():
        p = Path(p)
        out[name] = MapModel.load(p) if p.suffix == ".json" else osm.build_map(p)
    return out
