"""Generate player/tests/fixtures from the synthetic map and the 7 reference scenarios.

Ground-truth surface classifications come from Python so the TypeScript runtime can be tested for exact agreement
(the 'alignment' guarantee between the validator and the player).

    python scripts/make_player_fixtures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg import osm, synth                              # noqa: E402
from usg.mapmodel import MapModel                       # noqa: E402
from usg.sandbox import execute_script                  # noqa: E402
from usg.scenario_types import ARCHETYPES               # noqa: E402
import random                                           # noqa: E402
from usg.spec.monitor import Monitor, Sample            # noqa: E402

SPEC_CROSS_SCRIPT = """from usg.dsl import *
scenario = ScenarioBuilder('spec_cross', MAP, scenario_type='custom')
scenario.user(MAP.crossing_side('crossing_1', 'start', inset=6.0))
sig = scenario.signal_cycle('crossing_1', green=10, red=15, initial='red')
route = MAP.drive_route(MAP.crossings()[0]['road'], 0, 60, 'forward')
scenario.vehicle('Car1', route[0], route[1:], speed=7, start_when=when_time(2))
scenario.apply_spec({'tasks': [
  {'name': 'wait_then_cross', 'instruction': 'Wait for green, then cross.',
   'goal': {'op': 'then', 'args': [
       {'op': 'call', 'name': 'wait_for_green', 'args': {'zone': {'kind': 'crossing_side', 'id': 'crossing_1', 'side': 'start', 'r': 3.0}, 'signal': sig}},
       {'op': 'call', 'name': 'reach', 'args': {'zone': {'kind': 'crossing_side', 'id': 'crossing_1', 'side': 'end', 'r': 2.0}}}]},
   'safety': [{'op': 'call', 'name': 'obey_signal', 'args': {'zone': {'kind': 'crossing', 'id': 'crossing_1'}, 'signal': sig}}],
   'timeout': {'initial': 70, 'baseline': 110}}]})
"""

SPEC_LOOK_SCRIPT = """from usg.dsl import *
scenario = ScenarioBuilder('spec_look', MAP, scenario_type='custom')
scenario.user(MAP.crossing_side('crossing_1', 'start', inset=2.0))
route = MAP.drive_route(MAP.crossings()[0]['road'], 0, 60, 'forward')
scenario.vehicle('Car1', route[0], route[1:], speed=7, start_when=when_time(2))
scenario.apply_spec({'tasks': [
  {'name': 'check_traffic', 'instruction': 'Look at the approaching car.',
   'goal': {'op': 'call', 'name': 'look', 'args': {'entity': 'Car1', 'angle': 30, 'seconds': 25}},
   'timeout': {'initial': 30, 'baseline': 40}}]})
"""


# ------------------------------------------------------------------ random formulas + traces for the monitor parity test
def _rand_atom(r: random.Random) -> dict:
    k = r.choice(["in_zone", "in_zone", "on_surface", "near_path", "dist_le", "dist_ge", "look_at", "speed_le", "speed_ge",
                  "signal_is", "event", "true"])
    if k == "in_zone":
        z = r.choice(["disc", "rect", "entity"])
        zone = ({"kind": "disc", "x": r.uniform(-5, 15), "y": r.uniform(-5, 5), "r": r.uniform(0.5, 4)} if z == "disc" else
                {"kind": "rect", "cx": r.uniform(0, 10), "cy": r.uniform(-3, 3), "h": r.uniform(-3, 3), "hl": r.uniform(1, 5), "hw": r.uniform(1, 4)} if z == "rect" else
                {"kind": "entity", "name": r.choice(["A", "B", "Z"]), "r": r.uniform(1, 5)})
        return {"op": k, "zone": zone}
    if k == "on_surface":
        return {"op": k, "surface": r.choice(["walkable", "pedestrian_infra", "crosswalk", "road", "sidewalk"])}
    if k == "near_path":
        return {"op": k, "path": [[r.uniform(-3, 3), r.uniform(-3, 3)], [r.uniform(5, 15), r.uniform(-3, 3)], [r.uniform(15, 25), r.uniform(-3, 3)]], "tol": r.uniform(0.5, 3)}
    if k in ("dist_le", "dist_ge"):
        return {"op": k, "entity": r.choice(["A", "B", "Z"]), "d": r.uniform(0, 6)}
    if k == "look_at":
        n = {"op": k, "angle": r.uniform(10, 90)}
        if r.random() < 0.5:
            n["entity"] = r.choice(["A", "B", "Z"])
        else:
            n["point"] = [r.uniform(-5, 20), r.uniform(-5, 5)]
        return n
    if k in ("speed_le", "speed_ge"):
        return {"op": k, "v": r.uniform(0.3, 2.5)}
    if k == "signal_is":
        return {"op": k, "signal": r.choice(["s1", "s2"]), "state": r.choice(["green", "red"])}
    if k == "event":
        return {"op": k, "name": r.choice(["e1", "e2"])}
    return {"op": "true"}


def _rand_formula(r: random.Random, depth: int) -> dict:
    if depth <= 0 or r.random() < 0.25:
        return _rand_atom(r)
    op = r.choice(["not", "and", "or", "implies", "eventually", "always", "until", "prev", "eventually", "always"])

    def sub():
        return _rand_formula(r, depth - 1)

    if op == "not":
        return {"op": op, "arg": sub()}
    if op in ("and", "or"):
        return {"op": op, "args": [sub() for _ in range(r.randint(2, 3))]}
    if op == "implies":
        return {"op": op, "a": sub(), "b": sub()}
    if op == "prev":
        return {"op": op, "arg": sub(), "init": r.random() < 0.5}
    start = r.choice([0, 0, 0.1, 0.3])
    end = r.choice([None, start + r.choice([0.2, 0.5, 1.0, 2.0])])
    if op == "until":
        return {"op": op, "left": sub(), "right": sub(), "start": start, "end": end}
    return {"op": op, "arg": sub(), "start": start, "end": end}


def _rand_trace(r: random.Random, n: int) -> list:
    out, x, y, g = [], r.uniform(-2, 2), r.uniform(-2, 2), r.uniform(-3, 3)
    ev: set = set()
    sig = {"s1": r.choice(["green", "red"]), "s2": r.choice(["green", "red"])}
    for i in range(n):
        x += r.uniform(-0.1, 0.5)
        y += r.uniform(-0.3, 0.3)
        g += r.uniform(-0.6, 0.6)
        if r.random() < 0.15:
            sig[r.choice(["s1", "s2"])] = r.choice(["green", "red"])
        if r.random() < 0.08:
            ev.add(r.choice(["e1", "e2"]))
        ents = {"A": (r.uniform(-5, 20), r.uniform(-4, 4), r.uniform(-3, 3), 4.6, 2.0),
                "B": (r.uniform(-5, 20), r.uniform(-4, 4), r.uniform(-3, 3), 0.6, 0.6)}      # "Z" is never present
        out.append(Sample(x, y, g, r.uniform(0, 3), r.choice(["sidewalk", "road", "crosswalk", "ground", "path"]),
                          ents, dict(sig), frozenset(ev)))
    return out


def formula_cases(n_cases: int = 160) -> list:
    r = random.Random(20260710)
    cases = []
    for _ in range(n_cases):
        f = _rand_formula(r, r.randint(1, 4))
        tr = _rand_trace(r, 40)
        res = []
        for n in (4, 12, 40):
            for complete in (False, True):
                for k in (0, 2):
                    lo, hi = Monitor(tr[:n], 0.1, complete).rho(f, k)
                    res.append({"n": n, "complete": complete, "k": k, "lo": lo, "hi": hi})
        cases.append({"formula": f,
                      "samples": [{"x": s.x, "y": s.y, "gaze": s.gaze, "speed": s.speed, "surface": s.surface,
                                   "ents": {k: list(v) for k, v in s.ents.items()}, "signals": s.signals,
                                   "events": sorted(s.events)} for s in tr],
                      "results": res})
    return cases

SIGNAL_SCRIPT = """from usg.dsl import *
scenario = ScenarioBuilder('signal_cross', MAP, scenario_type='ptp_env')
scenario.user(MAP.crossing_side('crossing_1', 'start', inset=2.0))
scenario.signal_cycle('crossing_1', green=10, red=15, initial='red')
scenario.cross('crossing_1', 'start', 'Wait for green, then cross', timeout=60)
"""


def main() -> None:
    fx = ROOT / "player" / "tests" / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    d = osm.build_map(synth.synthetic_osm()).to_dict()
    m = MapModel.from_dict(json.loads(json.dumps(d)))          # the same rounded data the player loads
    (fx / "map.json").write_text(json.dumps(d), encoding="utf-8")

    x0, y0, x1, y1 = m.bounds
    samples, step, y = [], 2.5, y0 - 10
    while y <= y1 + 10:
        x = x0 - 10
        while x <= x1 + 10:
            xr, yr = round(x, 2), round(y, 2)
            samples.append([xr, yr, m.surface_at((xr, yr))])
            x += step
        y += step
    (fx / "surface_samples.json").write_text(json.dumps(samples), encoding="utf-8")

    scripts = {sid: a["template"] for sid, a in ARCHETYPES.items()}
    scripts["signal_cross"] = SIGNAL_SCRIPT
    scripts["spec_cross"] = SPEC_CROSS_SCRIPT
    scripts["spec_look"] = SPEC_LOOK_SCRIPT
    for name, code in scripts.items():
        res = execute_script(code, m, "map.xodr")
        assert res["ok"], (name, res)
        (fx / f"{name}.xosc").write_text(res["xosc"], encoding="utf-8")
    cases = formula_cases()
    (fx / "formula_cases.json").write_text(json.dumps(cases), encoding="utf-8")
    print(f"fixtures: {len(samples)} surface samples, {len(scripts)} scenarios, {len(cases)} formula cases -> {fx}")


if __name__ == "__main__":
    main()
