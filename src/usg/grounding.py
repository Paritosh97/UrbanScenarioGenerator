"""Hard checks that the request can be satisfied by THIS map, and that the generated scenario really uses what was asked.

1. ``missing_objects`` (before the model is called): the prompt names an object the map does not contain ("walk to the waste
   basket" on a map without one) -> the request is refused with what the map does offer.
2. ``grounding_errors`` (when a specification or script is submitted): for every object type the prompt names and the map has,
   at least one goal zone must lie near an instance of it; otherwise the submission is rejected and the nearest ids are listed.
"""
from __future__ import annotations

import re
from typing import Optional

from . import geo

NEAR = 6.0        # metres: a goal zone this close to an instance counts as "going to it"

# type -> (human name, regex, finder(MapQuery) -> list of {"id","pos"})
def _props(ptype):
    return lambda q: [{"id": p["id"], "pos": p["pos"]} for p in q.props(ptype)]


def _crossings(control=None):
    return lambda q: [{"id": c["id"], "pos": c["center"]} for c in q.crossings(control)]


OBJECTS: dict[str, tuple[str, re.Pattern, object]] = {
    "waste_basket": ("waste basket", re.compile(r"waste ?basket|trash ?(?:can|bin)|litter ?bin|rubbish ?bin|dust ?bin|\bbins?\b", re.I), _props("waste_basket")),
    "bench": ("bench", re.compile(r"\bbench(?:es)?\b", re.I), _props("bench")),
    "tree": ("tree", re.compile(r"\btrees?\b", re.I), _props("tree")),
    "street_lamp": ("street lamp", re.compile(r"street ?lamps?|lamp ?posts?|street ?lights?|\blamps?\b", re.I), _props("street_lamp")),
    "bollard": ("bollard", re.compile(r"\bbollards?\b", re.I), _props("bollard")),
    "bus_stop": ("bus stop", re.compile(r"bus ?stops?", re.I), _props("bus_stop")),
    "bicycle_parking": ("bicycle parking", re.compile(r"bicycle parking|bike (?:rack|parking|stand)s?", re.I), _props("bicycle_parking")),
    "zebra_crossing": ("zebra crossing", re.compile(r"zebra", re.I), _crossings("zebra")),
    "signal_crossing": ("signalised crossing (pedestrian light)",
                        re.compile(r"traffic ?light|pedestrian ?(?:light|signal)|green ?light|red ?light|signalised|signalized|\bsignals?\b|wait for (?:the )?green", re.I),
                        _crossings("signals")),
}
# a request for a crossing in general is satisfied by any crossing; handled separately
ANY_CROSSING = re.compile(r"\bcross(?:ing)?\b|\bcross the (?:road|street)\b", re.I)


def requested_objects(prompt: str) -> list[str]:
    return [k for k, (_n, rx, _f) in OBJECTS.items() if rx.search(prompt or "")]


def inventory(q) -> dict[str, int]:
    """How many instances of each requestable object the map has."""
    return {k: len(f(q)) for k, (_n, _rx, f) in OBJECTS.items()}


def inventory_text(q) -> str:
    inv = inventory(q)
    have = [f"{OBJECTS[k][0]} x{n}" for k, n in inv.items() if n]
    none = [OBJECTS[k][0] for k, n in inv.items() if not n]
    return "Objects on this map: " + (", ".join(have) or "none") + ("; NOT on this map: " + ", ".join(none) if none else "") + "."


def requested_ids_text(prompt: str, q, per_type: int = 3) -> str:
    """The real ids of the objects the request names, nearest to the map centre first, with a zone the model can copy. A small model invents ids
    ('prop_x112') and then loops on list_features; the ids are given up front instead. '' if the request names no object."""
    lines = []
    for k in requested_objects(prompt):
        inst = OBJECTS[k][2](q)
        if not inst:
            continue
        near = sorted(inst, key=lambda i: geo.dist(tuple(i["pos"]), (0.0, 0.0)))[:per_type]
        if k in ("zebra_crossing", "signal_crossing"):
            ex = '{"kind":"crossing_side","id":"%s","side":"end","r":2}' % near[0]["id"]
        else:
            ex = '{"kind":"feature","id":"%s","r":3}' % near[0]["id"]
        lines.append(f"{OBJECTS[k][0]}: " + ", ".join(f"{i['id']} at ({i['pos'][0]:.0f},{i['pos'][1]:.0f})" for i in near) + f". Zone example: {ex}")
    out = ""
    if lines:
        out = "Real ids for the objects in the request (use these exactly; do not invent ids):" + chr(10) + chr(10).join(lines)
    if ROAD_CUE.search(prompt or ""):                          # "stand on the road": the model invents coordinates, so give a verified one
        out += (chr(10) if out else "") + "The request asks for a spot ON THE ROAD. " + _road_hint(q._m if hasattr(q, "_m") else q) + \
            ". Do not add a safety rule that keeps the participant on the sidewalk."
    return out


def missing_objects(prompt: str, q) -> list[str]:
    """Object types the prompt names that the map does not contain (human names)."""
    inv = inventory(q)
    out = [OBJECTS[k][0] for k in requested_objects(prompt) if inv[k] == 0]
    if ANY_CROSSING.search(prompt or "") and not q.crossings() and "crossing" not in out:
        out.append("crossing")
    return out


def refusal_text(prompt: str, q) -> Optional[str]:
    miss = missing_objects(prompt, q)
    if not miss:
        return None
    return ("This map has no " + ", no ".join(miss) + f", so the request cannot be built here. {inventory_text(q)} "
            "Pick another area, or change the request.")


def grounding_errors(prompt: str, q, centres: list[tuple[float, float]]) -> list[str]:
    """Errors for each requested (and available) object type that no goal zone reaches."""
    out = []
    if not prompt:
        return out
    for k in requested_objects(prompt):
        name, _rx, finder = OBJECTS[k]
        inst = finder(q)
        if not inst:
            continue                                  # missing_objects() refuses these before generation
        reach = 14.0 if k in ("zebra_crossing", "signal_crossing") else NEAR     # a crossing is long: its far kerb is further from its centre
        if any(geo.dist(tuple(i["pos"]), c) <= reach for i in inst for c in centres):
            continue
        ref = centres[0] if centres else (0.0, 0.0)
        near = sorted(inst, key=lambda i: geo.dist(tuple(i["pos"]), ref))[:3]
        zone = ('{"kind":"feature","id":"%s","r":3}' % near[0]["id"]) if k not in ("zebra_crossing", "signal_crossing") else \
            ('{"kind":"crossing_side","id":"%s","side":"end","r":2}' % near[0]["id"])
        out.append(f"the request names a {name}, but no task goal is within {reach:g} m of one. The map has: "
                   + ", ".join(f"{i['id']} at ({i['pos'][0]:.0f},{i['pos'][1]:.0f})" for i in near)
                   + f". Make a goal zone at one of them, for example {zone}")
    return out


# ------------------------------------------------------------------ does the scenario do what the request explicitly says?
ROAD_CUE = re.compile(r"\b(?:on|onto) the (?:road|carriageway)\b|middle of the (?:road|street)|road surface|carriageway", re.I)
SIGNAL_CUE = re.compile(r"wait (?:for|until) (?:the )?(?:green|light|signal|pedestrian)|pedestrian (?:light|signal)|traffic ?light|green ?light", re.I)
LOOK_CUE = re.compile(r"\blook(?:s|ing)? (?:at|both ways|left|right|around|for)\b", re.I)
MOVER_CUE = re.compile(r"\b(?:car|bus|truck|van|vehicle|cyclist|bike)s? (?:approach|drive|come|speed|pass|is coming|are coming)|oncoming|approaching (?:car|bus|truck|vehicle|cyclist)|speeding", re.I)
PARKED_CUE = re.compile(r"parked (?:car|vehicle|truck|van)s?", re.I)


def intent_errors(prompt: str, ops: set, centres: list, model, axes: Optional[dict] = None) -> list[str]:
    """Errors for explicit cues in the request that the specification/scenario does not honour.

    ``ops``: atom operators used by all goal and safety formulas; ``centres``: goal-zone centres; ``axes``: the scenario's constraint
    axes (known only once the world script ran; static/dynamic cues are checked then)."""
    out = []
    p = prompt or ""
    if ROAD_CUE.search(p) and not any(model.surface_at(tuple(c)) == "road" for c in centres):
        out.append("the request says the participant must be ON THE ROAD, but no goal zone is on the road surface (a crossing's kerb is a sidewalk). "
                   "Put a goal zone on the carriageway and do not require a safety rule that keeps the participant on the sidewalk or off the road. "
                   + _road_hint(model))
    if SIGNAL_CUE.search(p) and "signal_is" not in ops:
        out.append("the request is about waiting for a light/signal, but the specification never uses a signal state; use wait_for_green and obey_signal "
                   "(or signal_is) with the crossing's signal name")
    if LOOK_CUE.search(p) and "look_at" not in ops:
        out.append("the request asks the participant to look at something, but the specification has no look_at; use the `look` or `look_point` definition")
    if MOVER_CUE.search(p):
        if axes is not None and axes.get("dynamic") != "movers":
            out.append("the request has traffic approaching, but no moving vehicle is kept clear of: create a moving vehicle (route + speed) and add a "
                       "collision_free/keep_clear rule for it (naming an entity such as car_1 in a collision_free rule is enough: the vehicle is created for you)")
        if axes is None and "dist_ge" not in ops:
            out.append("the request has traffic approaching, so the specification needs a rule that keeps the participant clear of the vehicle "
                       "(collision_free / keep_clear on its name)")
    if PARKED_CUE.search(p) and axes is not None and axes.get("static") != "obstacles":
        out.append("the request mentions parked cars, but no parked vehicle is avoided: create parked_vehicle(...) entities and add a collision_free rule for them (naming entities such as parked_1, parked_2 in collision_free rules is enough: they are created for you)")
    return out


def _road_hint(model) -> str:
    """A concrete goal zone on the carriageway (just past the first crossing), as an example the model can copy."""
    try:
        from .dsl import MapQuery
        q = MapQuery(model)
        length_of = {r["id"]: r.get("length", 0.0) for r in q.roads()}
        for c in sorted(q.crossings(), key=lambda c: length_of.get(c["road"], 0.0) < 40.0):     # crossings on real streets first, not on stub roads
            p = q.along_road(c["road"], c["road_s"] + 6.0, 0.0)
            if model.surface_at((p.x, p.y)) == "road":
                return f'Example (surface verified as road): {{"kind": "disc", "x": {p.x:.1f}, "y": {p.y:.1f}, "r": 2}}'
    except Exception:
        pass
    return "Use list_features / check_point to find a point whose surface is 'road'."


# ------------------------------------------------------------------ a corridor has to lie on the map and lead to the goal
def corridor_errors(doc: dict, centres: list, model, slack: float = 8.0) -> list[str]:
    """Errors for corridors (``path`` lists of [x, y] in ``near_path`` atoms and ``stay_near_path`` calls) that cannot belong to the task.

    The participant is placed at the start of a required corridor and must reach the goal while staying within ``tol`` of it, so the corridor
    has to start on walkable ground and pass the goal zone. A small model tends to invent short corridors near the map origin; the validator
    only discovers that after the world exists (margin of hundreds of metres), so it is reported here, at the specification, with a way out."""
    out: list[str] = []
    paths: list[tuple[list, float]] = []

    def walk(x):
        if isinstance(x, dict):
            p = x.get("path")
            if isinstance(p, list) and len(p) >= 2 and all(isinstance(q, (list, tuple)) and len(q) == 2 and all(isinstance(v, (int, float)) for v in q) for q in p):
                tol = x.get("tol", 2.0)
                paths.append((p, float(tol) if isinstance(tol, (int, float)) else 2.0))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(doc.get("tasks", []))
    for p, tol in paths:
        pts = [(float(q[0]), float(q[1])) for q in p]
        first = pts[0]
        if model.surface_at(first) not in ("sidewalk", "path", "ground", "crosswalk"):
            out.append(f"the corridor starts at ({first[0]:.0f},{first[1]:.0f}), which is {model.surface_at(first)}, not walkable ground; the participant starts at the "
                       "first point of a required corridor. Build the corridor from real coordinates (the points returned by plan_route, or a sidewalk or path feature).")
            continue
        if centres:
            d, c = min((geo.dist_to_polyline(pts, tuple(c)), c) for c in centres)
            if d > tol + slack:
                out.append(f"the corridor ({len(pts)} points from ({first[0]:.0f},{first[1]:.0f})) passes {d:.0f} m from the nearest goal zone at ({c[0]:.0f},{c[1]:.0f}), "
                           f"so the participant cannot reach the goal and stay within {tol:g} m of it. Build the corridor from real coordinates that lead from the "
                           "start to the goal, for example the points returned by plan_route.")
    return out


def surface_rule_errors(doc: dict, centres: list, model) -> list[str]:
    """``stay_on <surface>`` is broken by an ordinary walk when no goal zone lies on that surface (for example ``stay_on sidewalk`` with a goal on a crossing:
    a crossing is a crosswalk, not a sidewalk). Conservative: reported only when NO goal centre of the document is on the surface."""
    from .spec.monitor import SURFACE_SETS
    out: list[str] = []
    seen: set = set()

    def walk(x):
        if isinstance(x, dict):
            if x.get("name") == "stay_on" or x.get("op") == "on_surface":
                a = x.get("args", x)
                if isinstance(a, dict) and isinstance(a.get("surface"), str):
                    seen.add(a["surface"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for t in doc.get("tasks", []) if isinstance(doc, dict) else []:
        for f in (t.get("safety") or []) if isinstance(t, dict) else []:
            walk(f)
    if not centres:
        return out
    for s in sorted(seen):
        allowed = SURFACE_SETS.get(s)
        if allowed and not any(model.surface_at(tuple(c)) in allowed for c in centres):
            kinds = sorted({model.surface_at(tuple(c)) for c in centres})
            out.append(f"the safety rule stay_on '{s}' is broken by an ordinary walk: the goal zone is on {'/'.join(kinds)}, not on {s}. "
                       f"Use a surface class that contains the goal (for example 'pedestrian_infra' includes crossings), or move the goal zone onto {s} "
                       "(a crossing_side zone is the kerb).")
    return out
