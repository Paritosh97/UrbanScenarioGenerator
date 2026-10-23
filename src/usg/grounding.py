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
                       "collision_free/keep_clear rule for it")
        if axes is None and "dist_ge" not in ops:
            out.append("the request has traffic approaching, so the specification needs a rule that keeps the participant clear of the vehicle "
                       "(collision_free / keep_clear on its name)")
    if PARKED_CUE.search(p) and axes is not None and axes.get("static") != "obstacles":
        out.append("the request mentions parked cars, but no parked vehicle is avoided: create parked_vehicle(...) entities and add a collision_free rule for them")
    return out


def _road_hint(model) -> str:
    """A concrete goal zone on the carriageway (just past the first crossing), as an example the model can copy."""
    try:
        from .dsl import MapQuery
        q = MapQuery(model)
        for c in q.crossings():
            p = q.along_road(c["road"], c["road_s"] + 6.0, 0.0)
            if model.surface_at((p.x, p.y)) == "road":
                return f'Example (surface verified as road): {{"kind": "disc", "x": {p.x:.1f}, "y": {p.y:.1f}, "r": 2}}'
    except Exception:
        pass
    return "Use list_features / check_point to find a point whose surface is 'road'."
