"""Deterministic safety nets around the language model, so that the pipeline can always return a valid scenario.

A model that writes a good specification can still fail at the plumbing (a wrong call to the map API, a missing entity), and a small model sometimes
stops answering altogether. Two nets catch this, in order, and every result records which one produced it (``tier``):

* **model**     the model's own submission was accepted (no net involved);
* **assisted**  the model's specification was accepted but its world script kept failing, so the harness wrote the world script from what the
                specification needs (``world_script``): the task rules are still the model's;
* **fallback**  the model produced nothing usable, so the harness submits the reference script of the most likely scenario type (``fallback_script``).
                It is valid by construction on every map that has the features the type needs, but it need not match the request: report it
                separately (``adherent`` is computed as usual and is usually false).

Whether to use the nets is a choice of the experiment (``ToolServer.assist``): off, to measure the model alone; on, to guarantee a valid output.
"""
from __future__ import annotations

import re
from typing import Optional

from . import geo
from .scenario_types import ARCHETYPES, classify

VEHICLE_WORDS = ("car", "veh", "bus", "truck", "van", "taxi", "bike", "scooter")
PARKED_WORDS = ("park", "obst", "block")
WALKER_WORDS = ("ped", "walk", "person", "kid", "child", "people", "man", "woman")


def entity_kind(name: str) -> str:
    n = name.lower()
    if any(n.startswith(w) for w in PARKED_WORDS):
        return "parked"
    if any(n.startswith(w) for w in WALKER_WORDS):
        return "walker"
    return "vehicle"


def _anchor_crossing(doc: dict, q) -> Optional[dict]:
    """The crossing the world should be built around: the first one a zone of the specification names, else the one nearest to the goal."""
    ids: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("kind") in ("crossing", "crossing_side") and isinstance(x.get("id"), str):
                ids.append(x["id"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(doc.get("tasks", []))
    crossings = q.crossings()
    for cid in ids:
        for c in crossings:
            if c["id"] == cid:
                return c
    pts: list[tuple] = []

    def zones(x):
        if isinstance(x, dict):
            if x.get("kind") == "disc":
                pts.append((x["x"], x["y"]))
            elif x.get("kind") == "feature" and isinstance(x.get("id"), str):
                try:
                    pts.append(tuple(q.feature(x["id"])["pos"]))
                except Exception:
                    pass
            for v in x.values():
                zones(v)
        elif isinstance(x, list):
            for v in x:
                zones(v)
    zones(doc.get("tasks", []))
    if pts and crossings:
        return min(crossings, key=lambda c: geo.dist(tuple(c["center"]), pts[0]))
    return crossings[0] if crossings else None


def world_script(doc: dict, needs: dict, q, name: str = "auto_world") -> Optional[str]:
    """A stage-B world script written from what an accepted specification needs: the signals and the named vehicles / walkers / parked cars.

    None if the specification names a signal that the map does not have (the rules cannot be satisfied by any world; the model has to change them)."""
    cr = _anchor_crossing(doc, q)
    L = ["from usg.dsl import *",
         f"scenario = ScenarioBuilder({name!r}, MAP, scenario_type='custom', description='World built by the harness around the model specification.')",
         "handles = scenario.apply_spec(SPEC)"]
    crossings = q.crossings()
    map_signals = {x["id"] for x in q.signals()}
    for sig in needs.get("signals", []):
        owner = next((c for c in crossings if c.get("signal_id") == sig or f"{c['id']}_ped" == sig), None)
        if owner is None and sig not in map_signals:
            return None
        L.append(f"scenario.signal_cycle({(owner['id'] if owner else sig)!r}, green=15, red=20, initial='red')")
    ents = sorted(needs.get("entities", {}))
    if ents:
        if cr is not None:
            cid, road, s_ = cr["id"], cr["road"], cr["road_s"]
        else:                                                       # no crossing on the map: build around the nearest road of the first goal
            cid, road, s_ = None, q.roads()[0]["id"], 0.0
        L.append(f"road, s = {road!r}, {float(s_)!r}")
        L.append("length = MAP.road(road)['length']")
        n_car = n_park = 0
        for n in ents:
            kind = entity_kind(n)
            if kind == "vehicle":
                off = 30.0 + 8.0 * n_car
                L.append(f"route = MAP.drive_route(road, max(0.0, s - {off}), min(length, s + {off}), 'forward')")
                L.append(f"scenario.vehicle({n!r}, route[0], route[1:], speed=8.0, model='car_white', start_when=when_task_starts(handles[0]))")
                n_car += 1
            elif kind == "parked":
                L.append(f"slots = MAP.kerb_slots(road, 'right', 7.0)")
                L.append(f"scenario.parked_vehicle({n!r}, slots[{min(n_park, 2)} % max(1, len(slots))] if slots else MAP.along_road(road, s + 8.0, 4.0), 'car_red')")
                n_park += 1
            else:
                if cid is not None:
                    L.append(f"a, b = MAP.crossing_side({cid!r}, 'start', inset=2.0), MAP.crossing_side({cid!r}, 'end', inset=2.0)")
                else:
                    L.append("a, b = MAP.sidewalk_at(road, 'right', max(5.0, s)), MAP.sidewalk_at(road, 'right', min(length, s + 20.0))")
                L.append(f"scenario.walker({n!r}, a, [b], speed=1.3, start_when=when_task_starts(handles[0]))")
    return "\n".join(L) + "\n"


def fallback_script(prompt: str) -> tuple[str, str]:
    """(scenario type, reference script) for the most likely type of the request."""
    t = classify(prompt)[0]
    return t, ARCHETYPES[t]["template"]


_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def safe_names(needs: dict) -> bool:
    """The synthesised script writes names with repr(); this only guards against names that are not plain identifiers."""
    return all(_NAME.match(n) for n in list(needs.get("entities", {})) + list(needs.get("signals", [])))
