"""The whole scenario as ONE data document (L1): start, signals, vehicles and tasks. No script is executed.

    {"start": [x, y], "signals": [{"crossing", "green", "red", "initial"}],
     "vehicles": [{"name", "type", "at": [x, y]} | {"name", "type", "roads": [...], "meet": crossing id or [x, y], "speed"}],
     "tasks": [{"name", "instruction", "goal", "safety", "timeout", "after" | "mode"}]}

``build`` turns it into a scenario through the same builder the simulator export uses. The participant faces the first walking target.
"""
from __future__ import annotations

import math

from .. import geo
from ..dsl import MapQuery, Place, ScenarioBuilder
from . import formula as F

KEYS = {"start", "signals", "vehicles", "tasks"}
# checks of the map validator that use the whole-map walking graph; a window scenario is checked with its own path search instead
ROUTING = {"no_route", "timeout_too_short", "timeout_long", "far_from_crossing"}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _xy(v, what: str) -> tuple:
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(map(_num, v))):
        raise F.SpecError(f"{what}: needs [x, y]")
    return float(v[0]), float(v[1])


def _facing(doc: dict, MAP: MapQuery, start: tuple) -> float:
    for t in doc["tasks"]:
        goal = F.resolve(F.prepare(t.get("goal"), None, "goal"), MAP)
        for z in F.zones_in(goal):
            if z["kind"] in ("disc", "rect"):
                p = (z["x"], z["y"]) if z["kind"] == "disc" else (z["cx"], z["cy"])
                if geo.dist(p, start) > 0.5:
                    return geo.heading(start, p)
    return 0.0


def build(doc: dict, model) -> ScenarioBuilder:
    """Raises ``F.SpecError`` / ``ValueError`` / ``KeyError`` for a document that cannot be built on this map."""
    if not isinstance(doc, dict) or set(doc) - KEYS or "start" not in doc or not isinstance(doc.get("tasks"), list) or not doc["tasks"]:
        raise F.SpecError(f"document: an object with the keys {sorted(KEYS)}; 'start' and 'tasks' are required")
    MAP = MapQuery(model)
    sc = ScenarioBuilder("scenario", MAP, scenario_type="custom")
    start = _xy(doc["start"], "start")
    sc.user(Place(start[0], start[1], 0.0, _facing(doc, MAP, start)))
    for s in doc.get("signals", []):
        sc.signal_cycle(s["crossing"], green=s.get("green", 15), red=s.get("red", 20), initial=s.get("initial", "red"))
    for v in doc.get("vehicles", []):
        name, kind = v["name"], v.get("type", "car_white")
        if "at" in v:
            at = _xy(v["at"], f"vehicle {name}.at")
            sc.parked_vehicle(name, Place(at[0], at[1]), kind)
        else:
            meet = v["meet"] if isinstance(v["meet"], str) else Place(*_xy(v["meet"], f"vehicle {name}.meet"))
            if not _num(v.get("speed")) or v["speed"] <= 0:
                raise F.SpecError(f"vehicle {name}: 'speed' must be a number > 0")
            sc.approaching_vehicle(name, v["roads"], meet=meet, speed=float(v["speed"]), model=kind)
    sc.apply_spec({"tasks": doc["tasks"]}, 1)
    return sc


def check(doc: dict, model) -> tuple[dict, list]:
    """(built scenario, errors of the map validator without the whole-map routing checks)."""
    from ..validate import validate

    spec = build(doc, model).to_spec()
    return spec, [f"{i.code}: {i.message}" for i in validate(spec, model) if i.severity == "error" and i.code not in ROUTING]
