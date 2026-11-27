"""L1 scenario records of a 30 x 30 m map window: sample a typed record, find its paths, render request and reference reply,
and prove the reference on a simulated walk. ``verify`` judges another reply against a record.

A record is accepted only if
  1. the reference document builds on the map and passes the map validator (entities on legal surfaces, vehicles on roads);
  2. every leg has a path on the window grid that respects buildings, barriers, parked cars and the rules (``walk.py``);
  3. on the timed walk along these paths every goal is reached and no rule is broken, within the time limits;
  4. no task is already satisfied when it starts, every rule can matter, and each vehicle the walker must look at is visible;
  5. leaving out any task's work, or breaking the order or the signal rule, makes the specification fail (it is not vacuous).

``window``/``M`` are the outputs of ``window.build`` and ``window.localise``.
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from itertools import combinations, permutations, product
from typing import Optional

from .. import geo
from ..dsl import MapQuery
from ..spec import formula as F
from ..spec import scene
from ..spec.monitor import dist_to_obb
from . import walk as K
from . import window as W

# fixed defaults, stated once in the system prompt
R_PLACE, R_SIDE, INSET = 1.5, 1.5, 1.5
COLLISION_D = 0.3
AVOID_R = 2.0
LOOK_ANGLE, LOOK_S = 45, 12
GREEN, RED, INITIAL = 15, 20, "red"
LIMIT, BASELINE = 60, 90
MAX_TASK_S = 55.0                       # the reference walk of one task has to leave this much room below the limit
POSITION_TOL = 1.0

STEPS = ("reach", "reach_within", "stay", "either", "look", "wait", "cross")
VISITS = {"reach", "reach_within", "stay", "either"}
RULES = ("keep_distance", "avoid_area", "stay_on_sidewalk", "near_line", "obey_signal", "look_before_road")
VEHICLE_RULES = {"keep_distance", "look_before_road"}
# combinations never generated for training or validation (test set only)
HELD_OUT = [{"wait", "parked"}, {"near_line", "moving"}, {"stay", "stay_on_sidewalk"}]

MODELS = {"car": ["car_white", "car_red", "car_blue", "car_yellow"], "van": ["van_red"], "bus": ["bus_blue"], "truck": ["truck_yellow"]}
MODEL_WEIGHTS = (6, 2, 1, 1)


class Reject(Exception):
    """The window cannot host this record; the message is the reason, counted in the statistics."""


def _r(p) -> list:
    return [round(float(p[0]), 1), round(float(p[1]), 1)]


def _at(p) -> str:
    return f"({W.num(p[0])}, {W.num(p[1])})"


# ------------------------------------------------------------------ types
def valid_type(steps: tuple, order: str, rules: tuple, vehicle: str, flags: dict) -> bool:
    crosses = steps.count("cross")
    if crosses > (1 if flags["crossing"] else 0) or steps.count("wait") > (1 if flags["signal"] else 0) or steps.count("look") > 1:
        return False
    if "wait" in steps and (steps.index("wait") + 1 >= len(steps) or steps[steps.index("wait") + 1] != "cross"):
        return False
    if "look" in steps and (vehicle == "none" or (steps[-1] == "look" and len(steps) > 1)):
        return False
    if "stay_on_sidewalk" in rules and crosses:
        return False
    if "obey_signal" in rules and not (crosses and flags["signal"]):
        return False
    if "look_before_road" in rules and (not crosses or "look" in steps):
        return False
    if "near_line" in rules and (order == "any" or "either" in steps):
        return False
    if VEHICLE_RULES & set(rules) and vehicle == "none":
        return False
    if vehicle != "none" and not flags["road"]:
        return False
    return not (vehicle != "none" and "look" not in steps and not VEHICLE_RULES & set(rules))


def features(steps, rules, vehicle) -> set:
    return set(steps) | set(rules) | ({vehicle} if vehicle != "none" else set())


def is_held_out(steps, rules, vehicle) -> bool:
    f = features(steps, rules, vehicle)
    return any(c <= f for c in HELD_OUT)


_TYPE_CACHE: dict = {}


def types(flags: dict, n: int) -> list:
    """All (steps, order, rules, vehicle) with ``n`` steps that a window with these flags can host."""
    key = (flags["crossing"], flags["signal"], flags["road"], n)
    if key not in _TYPE_CACHE:
        out = {}
        for steps in product(STEPS, repeat=n):
            if steps.count("cross") > 1 or steps.count("wait") > 1 or steps.count("look") > 1:
                continue
            orders = ["one"] if n == 1 else ["sequence"] + (["ordered", "any"] if set(steps) <= VISITS else [])
            for order in orders:
                for k in range(3):
                    for rules in combinations(RULES, k):
                        for v in ("none", "parked", "moving"):
                            if valid_type(steps, order, rules, v, flags):
                                s = tuple(sorted(steps)) if order == "any" else steps
                                out[(s, order, rules, v)] = None
        _TYPE_CACHE[key] = list(out)
    return _TYPE_CACHE[key]


class Balance:
    """Draws types so that steps, rules, orders and vehicle settings are used about equally often among the accepted records."""

    def __init__(self, step_weights=((1, 0.3), (2, 0.4), (3, 0.3)), rule_weights=((0, 0.2), (1, 0.4), (2, 0.4))):
        self.use: Counter = Counter()
        self.step_weights, self.rule_weights = step_weights, rule_weights

    def draw(self, flags: dict, rng: random.Random, held: bool) -> Optional[tuple]:
        n = rng.choices([w[0] for w in self.step_weights], [w[1] for w in self.step_weights])[0]
        pool = [t for t in types(flags, n) if is_held_out(t[0], t[2], t[3]) == held]
        if not pool:
            return None
        k = rng.choices([w[0] for w in self.rule_weights], [w[1] for w in self.rule_weights])[0]
        pool = [t for t in pool if len(t[2]) == k] or pool
        picks = rng.sample(pool, min(8, len(pool)))

        def load(t):
            parts = list(t[0]) + list(t[2]) + [t[1], t[3]]
            return sum(self.use[p] for p in parts) / len(parts) + 3 * self.use[t]
        return min(picks, key=load)

    def accept(self, t: tuple) -> None:
        self.use.update(list(t[0]) + list(t[2]) + [t[1], t[3]])
        self.use[t] += 1


# ------------------------------------------------------------------ one window
class Window:
    def __init__(self, window_id: str, window: dict, M):
        self.id, self.window, self.M = window_id, window, M
        self.MAP = MapQuery(M)
        self.grid = K.Grid(window, M)
        e = window["elements"]
        self.roads = [r["id"] for r in e["roads"] if not r["passage"]]
        self.crossings = []                             # usable crossings with both sides in the window on walkable ground
        for c in e["crossings"]:
            if not c["road"]:
                continue
            sides = {s: self.side(c["id"], s) for s in ("start", "end")}
            if all(max(map(abs, p)) <= W.H - 0.5 and self.grid.surface_at(p) in K.FREE for p in sides.values()):
                self.crossings.append({"id": c["id"], "road": c["road"], "signal": c["control"] == "signals", "sides": sides})
        self.flags = {"crossing": bool(self.crossings), "signal": any(c["signal"] for c in self.crossings), "road": bool(self.roads)}

    def side(self, crossing: str, side: str) -> tuple:
        p = self.MAP.crossing_side(crossing, side, inset=INSET)
        return (round(p.x, 1), round(p.y, 1))

    def signal_name(self, crossing: str) -> str:
        return self.M.get(crossing).signal_id or f"{crossing}_ped"

    def point(self, place) -> tuple:
        return self.M.feature_point(place)[0] if isinstance(place, str) else tuple(place)

    def places(self, tree: dict, rng: random.Random, surfaces=("sidewalk", "path")) -> list:
        """Objects and walkable points reachable in ``tree``: [(place, position, path length)]."""
        out = []
        for o in self.window["elements"]["objects"]:
            p = self.point(o["id"])
            c = K.cell(p)
            near = [(c[0] + i, c[1] + j) for i in (-2, -1, 0, 1, 2) for j in (-2, -1, 0, 1, 2)]
            costs = [tree[q][0] for q in near if q in tree and geo.dist(K.xy(q), p) <= R_PLACE - 0.5]
            if costs and max(map(abs, p)) <= W.H - 0.5:
                out.append((o["id"], p, min(costs)))
        cells = [c for c in tree if self.grid.surface[c] in surfaces and max(map(abs, K.xy(c))) <= W.H - 1.5]
        for c in rng.sample(cells, min(40, len(cells))):
            p = tuple(_r(K.xy(c)))
            out.append((list(p), p, tree[c][0]))
        rng.shuffle(out)
        return out


# ------------------------------------------------------------------ instantiate a type on a window
def _walk_cells(w: Window, surfaces) -> list:
    return [c for c, s in w.grid.surface.items() if s in surfaces and max(map(abs, K.xy(c))) <= W.H - 1.5]


def _parked(w: Window, road: str, rng: random.Random, count: int, keep_off: list, near: list) -> list:
    spots = []
    for side in ("left", "right"):
        for p in w.MAP.kerb_slots(road, side, 3.0):
            q = (p.x, p.y)
            if max(map(abs, q)) > W.H - 1.5 or any(geo.dist(q, a) < 4.5 for a in keep_off):
                continue
            if w.grid.surface_at(q) != "road":
                continue
            spots.append((min(geo.dist(q, a) for a in near), q))
    spots.sort()
    spots = spots[:max(count * 3, 4)]                    # close to where the walker goes, so that it matters
    rng.shuffle(spots)
    out: list = []
    for _, q in spots:
        if len(out) < count and all(geo.dist(q, v) > 6.5 for v in out):
            out.append(q)
    return out


def instantiate(w: Window, t: tuple, rng: random.Random) -> dict:
    steps, order, rules, vehicle = t
    rec: dict = {"window": w.id, "steps": [], "order": order, "rules": [], "vehicles": [], "signal": None}
    cross_at = steps.index("cross") if "cross" in steps else None
    walkable = set(K.FREE)
    surfaces = ("sidewalk",) if "stay_on_sidewalk" in rules else ("sidewalk", "path")
    free = lambda c: w.grid.surface[c] in walkable and (surfaces != ("sidewalk",) or c in w.grid.sidewalk)  # noqa: E731
    on_road = steps == ("reach",) and not rules and bool(w.roads) and rng.random() < 0.15
    cross = None
    if cross_at is not None:
        options = [c for c in w.crossings if c["signal"] or not ({"wait"} & set(steps) or "obey_signal" in rules)]
        if not options:
            raise Reject("no suitable crossing")
        if rng.random() < 0.7:
            options = [c for c in options if c["signal"]] or options
        cross = rng.choice(options)
        side = rng.choice(["start", "end"])
        near, far = cross["sides"][side], cross["sides"]["end" if side == "start" else "start"]
        tree, _ = w.grid.search(near, free)
        starts = [c for c, (d, _) in tree.items() if 3.0 <= d <= 14.0 and geo.dist(K.xy(c), near) > R_SIDE + 1.0
                  and w.grid.surface[c] in surfaces and free(c) and max(map(abs, K.xy(c))) <= W.H - 1.0]
        if not starts:
            raise Reject("no start position near the crossing")
        start = tuple(_r(K.xy(rng.choice(starts))))
        if geo.dist(start, far) <= R_SIDE + 1.0:
            raise Reject("start too close to the far side")
    else:
        cells = [c for c in _walk_cells(w, surfaces) if free(c)]
        if not cells:
            raise Reject("no walkable start")
        start = tuple(_r(K.xy(rng.choice(cells))))
    rec["start"] = list(start)
    if not (free(K.cell(start)) and w.grid.surface_at(start) in surfaces):
        raise Reject("start not on walkable ground")

    # places: before the crossing from the start's side, after it from the far side
    here_tree, _ = w.grid.search(start, free)
    pools = {False: w.places(here_tree, rng, surfaces)}
    if cross is not None:
        far_tree, _ = w.grid.search(far, free)
        pools[True] = w.places(far_tree, rng, surfaces)
    taken: list = [start]
    if cross is not None:
        taken += [near, far]

    def pick(after: bool, last: tuple) -> tuple:
        for place, p, _ in pools[after]:
            if all(geo.dist(p, q) >= 4.0 for q in taken) and 4.0 <= geo.dist(last, p) <= 22.0:
                taken.append(p)
                return place, p
        raise Reject("not enough distinct reachable places")

    last = start
    for i, kind in enumerate(steps):
        after = cross_at is not None and i > cross_at
        s: dict = {"kind": kind}
        if kind in ("reach", "reach_within", "stay"):
            if on_road:
                road_cells = [c for c, v in w.grid.surface.items() if v == "road" and max(map(abs, K.xy(c))) <= W.H - 1.5
                              and 4.0 <= geo.dist(K.xy(c), start) <= 15.0]
                if not road_cells:
                    raise Reject("no road point")
                p = tuple(_r(K.xy(rng.choice(road_cells))))
                if w.grid.surface_at(p) != "road":
                    raise Reject("no road point")
                s.update(place=list(p), on_road=True)
            else:
                s["place"], p = pick(after, last)
            if kind == "stay":
                s["seconds"] = rng.choice([3, 5, 8, 10])
            if kind == "reach_within":
                s["seconds"] = None                         # set from the path length
            last = p
        elif kind == "either":
            a, pa = pick(after, last)
            b, pb = pick(after, last)
            s["places"] = [a, b]
            last = pa if geo.dist(last, pa) <= geo.dist(last, pb) else pb
        elif kind in ("wait", "cross"):
            s.update(crossing=cross["id"], side=side)
            last = far if kind == "cross" else near
        elif kind == "look":
            s["entity"] = "Car1"
        rec["steps"].append(s)

    if cross is not None and cross["signal"]:
        green, red = rng.choice([(GREEN, RED), (GREEN, RED), (12, 18), (10, 25), (20, 15), (15, 10)])
        rec["signal"] = {"crossing": cross["id"], "green": green, "red": red, "initial": INITIAL}

    targets = [w.point(p) for s in rec["steps"] for p in ([s["place"]] if "place" in s else s.get("places", []))]
    route = [start] + ([near, far] if cross is not None else []) + targets
    if vehicle == "parked":
        road = cross["road"] if cross is not None else rng.choice(w.roads)
        count = 2 if "keep_distance" in rules and "look" not in steps and "look_before_road" not in rules and rng.random() < 0.25 else 1
        spots = _parked(w, road, rng, count, [start] + targets + ([near, far] if cross else []), route)
        if not spots:
            raise Reject("no room for a parked vehicle")
        for i, q in enumerate(spots):
            rec["vehicles"].append({"name": f"Car{i + 1}", "type": rng.choices(list(MODELS), MODEL_WEIGHTS)[0], "moving": False, "at": _r(q)})
        if "keep_distance" in rules and cross is None:
            line = [start] + targets
            if all(geo.dist_to_polyline(line, v["at"]) > 8.0 for v in rec["vehicles"]):
                raise Reject("the vehicle is too far from the walk to matter")
    elif vehicle == "moving":
        kind = rng.choices(list(MODELS), MODEL_WEIGHTS)[0]
        if cross is not None:
            road, meet = cross["road"], cross["id"]
        else:
            pts = [(r["id"], tuple(_r(q))) for r in w.window["elements"]["roads"] if not r["passage"] for q in W.samples(r["line"], 2.0)]
            pts = [(r, q) for r, q in pts if max(map(abs, q)) <= W.H - 2 and min(geo.dist(q, a) for a in route) <= 10.0]
            if not pts:
                raise Reject("no road near the walk for a moving vehicle")
            road, meet = rng.choice(pts)
            meet = list(meet)
        rec["vehicles"].append({"name": "Car1", "type": kind, "moving": True, "roads": [road], "meet": meet,
                                "speed": rng.choice([3, 4, 5, 6, 7, 8])})

    for kind in rules:
        r: dict = {"kind": kind}
        if kind == "keep_distance":
            r["d"] = rng.choice([COLLISION_D, COLLISION_D, 1.0, 1.5])
        elif kind == "avoid_area":
            r["place"] = None                               # chosen next to the unrestricted walk
        elif kind == "near_line":
            r["path"] = [list(start)] + ([list(near), list(far)] if cross is not None and cross_at == 0 else [])
            if cross is not None and cross_at > 0:
                # the line follows the order of the walk
                seq = [list(start)]
                for s in rec["steps"]:
                    if s["kind"] == "cross":
                        seq += [list(near), list(far)]
                    elif "place" in s:
                        seq.append(_r(w.point(s["place"])))
                r["path"] = seq
            else:
                after_cross = False
                for s in rec["steps"]:
                    after_cross |= s["kind"] == "cross"
                    if "place" in s:
                        r["path"].append(_r(w.point(s["place"])))
            if len(r["path"]) < 2:
                raise Reject("no line to follow")
            r["width"] = rng.choice([2.0, 2.5, 3.0])
        rec["rules"].append(r)
    return rec


# ------------------------------------------------------------------ reference formulas and document
def zone(place) -> dict:
    return {"kind": "feature", "id": place, "r": R_PLACE} if isinstance(place, str) else \
        {"kind": "disc", "x": place[0], "y": place[1], "r": R_PLACE}


def side_zone(crossing: str, side: str) -> dict:
    return {"kind": "crossing_side", "id": crossing, "side": side, "inset": INSET, "r": R_SIDE}


def call(name: str, **args) -> dict:
    return {"op": "call", "name": name, "args": args}


def _in(z) -> dict:
    return {"op": "in_zone", "zone": z}


def goal_formula(s: dict, signal: Optional[str]) -> dict:
    k = s["kind"]
    if k == "reach":
        return call("reach", zone=zone(s["place"]))
    if k == "reach_within":
        return call("reach_within", zone=zone(s["place"]), seconds=s["seconds"])
    if k == "stay":
        return call("hold", zone=zone(s["place"]), seconds=s["seconds"])
    if k == "either":
        return {"op": "eventually", "arg": {"op": "or", "args": [_in(zone(p)) for p in s["places"]]}}
    if k == "look":
        return call("look", entity=s["entity"], angle=LOOK_ANGLE, seconds=LOOK_S)
    if k == "wait":
        return call("wait_for_green", zone=side_zone(s["crossing"], s["side"]), signal=signal)
    return call("cross", far_zone=side_zone(s["crossing"], "end" if s["side"] == "start" else "start"))


def _step_zones(s: dict) -> list:
    return [zone(p) for p in ([s["place"]] if "place" in s else s.get("places", []))]


def safety_formulas(rec: dict, i: int, signal: Optional[str]) -> list:
    """Rules of task ``i``: general rules on every task, signal and look-before-road on the crossing task, order rules on earlier tasks."""
    s = rec["steps"][i]
    out = []
    for r in rec["rules"]:
        k = r["kind"]
        if k == "keep_distance":
            out += [call("collision_free", entity=v["name"], r=r["d"]) for v in rec["vehicles"]]
        elif k == "avoid_area":
            out.append({"op": "always", "arg": {"op": "not", "arg": _in(dict(zone(r["place"]), r=AVOID_R))}})
        elif k == "stay_on_sidewalk":
            out.append(call("stay_on", surface="sidewalk"))
        elif k == "near_line":
            out.append(call("stay_near_path", path=r["path"], tol=r["width"]))
        elif k == "obey_signal" and s["kind"] == "cross":
            out.append(call("obey_signal", zone={"kind": "crossing", "id": s["crossing"]}, signal=signal))
        elif k == "look_before_road" and s["kind"] == "cross":
            out.append({"op": "until", "left": {"op": "not", "arg": {"op": "on_surface", "surface": "road"}},
                        "right": {"op": "look_at", "entity": rec["vehicles"][0]["name"], "angle": LOOK_ANGLE}})
    if rec["order"] == "ordered":
        for later in rec["steps"][i + 1:]:
            out += [{"op": "always", "arg": {"op": "not", "arg": _in(z)}} for z in _step_zones(later)]
    return out


TEXT = {"reach": "Walk to the target.", "reach_within": "Reach the target in time.", "stay": "Go to the target and stay.",
        "either": "Walk to one of the two targets.", "look": "Look at the vehicle.", "wait": "Wait for green.", "cross": "Cross the street."}


def document(rec: dict, w: Window, models: Optional[dict] = None) -> dict:
    signal = w.signal_name(rec["signal"]["crossing"]) if rec["signal"] else None
    doc: dict = {"start": rec["start"]}
    if rec["signal"]:
        s = rec["signal"]
        doc["signals"] = [{"crossing": s["crossing"], "green": s["green"], "red": s["red"], "initial": s["initial"]}]
    if rec["vehicles"]:
        doc["vehicles"] = []
        for v in rec["vehicles"]:
            d = {"name": v["name"], "type": (models or {}).get(v["name"], MODELS[v["type"]][0])}
            d.update({"roads": v["roads"], "meet": v["meet"], "speed": v["speed"]} if v["moving"] else {"at": v["at"]})
            doc["vehicles"].append(d)
    names = [f"t{i + 1}_{s['kind']}" for i, s in enumerate(rec["steps"])]
    doc["tasks"] = []
    for i, s in enumerate(rec["steps"]):
        t: dict = {"name": names[i], "instruction": TEXT[s["kind"]], "goal": goal_formula(s, signal)}
        safety = safety_formulas(rec, i, signal)
        if safety:
            t["safety"] = safety
        t["timeout"] = {"initial": LIMIT, "baseline": BASELINE}
        if rec["order"] in ("sequence", "ordered") and i:
            t["after"] = [names[i - 1]]
        elif rec["order"] == "any":
            t["mode"] = "parallel"
        doc["tasks"].append(t)
    return doc


# ------------------------------------------------------------------ the walk
class Plan:
    """The walk of a record on a window. Flags produce the variant walks that break one thing (used to test specifications)."""

    def __init__(self, rec: dict, w: Window, spec: dict, *, ignore=(), skip=None, order=None, idle=0.0):
        self.rec, self.w, self.spec = rec, w, spec
        self.ignore, self.skip, self.idle = set(ignore), skip, idle
        self.order = order
        self.walker = K.Walker(w.grid, spec)
        self.segments: dict = {}                        # step index -> (first sample, last sample)
        parked = [self.walker.movers[v["name"]].at(0.0) for v in rec["vehicles"] if not v["moving"]]
        keep = next((r["d"] for r in rec["rules"] if r["kind"] == "keep_distance"), COLLISION_D)
        self.clear = max(keep, COLLISION_D) + 0.35
        # a walker who ignores the distance rule only avoids walking through a vehicle
        self.boxes = [(e, 0.05 if "keep_distance" in self.ignore else self.clear) for e in parked]

    def allowed(self, i: int, road: bool = False, crossing: Optional[str] = None):
        rec, g = self.rec, self.w.grid
        rules = {r["kind"]: r for r in rec["rules"] if r["kind"] not in self.ignore}
        rect = F.resolve_zone({"kind": "crossing", "id": crossing}, self.w.MAP) if crossing else None
        discs = []
        if "avoid_area" in rules and rules["avoid_area"]["place"] is not None:
            discs.append((self.w.point(rules["avoid_area"]["place"]), AVOID_R + 0.35))
        if rec["order"] == "ordered" and "order" not in self.ignore:
            for later in rec["steps"][i + 1:]:
                for p in ([later["place"]] if "place" in later else later.get("places", [])):
                    discs.append((self.w.point(p), R_PLACE + 0.35))
        line = rules.get("near_line")
        sidewalk = "stay_on_sidewalk" in rules
        ends = []
        if crossing:
            ends = [self.w.side(crossing, "start"), self.w.side(crossing, "end")]

        def ok(c) -> bool:
            s, p = g.surface[c], K.xy(c)
            if sidewalk:
                if c not in g.sidewalk:
                    return False
            elif s not in K.FREE:
                if rect is not None:
                    if not (s in ("crosswalk", "road") and K.in_rect(p, rect, 0.2)):
                        return False
                elif not (road and s in ("road", "crosswalk")):
                    return False
            if any(dist_to_obb(p, (e[0], e[1]), e[2], e[3], e[4]) < d for e, d in self.boxes):
                return False
            if any(geo.dist(p, q) < r for q, r in discs):
                return False
            return line is None or geo.dist_to_polyline([tuple(q) for q in line["path"]], p) <= line["width"] - 0.3
        if not crossing:
            return ok
        return ok

    def go(self, i: int, target: tuple, radius: float, **kw) -> list:
        allowed = self.allowed(i, **kw)
        path = self.w.grid.path(self.walker.p, lambda p: geo.dist(p, target) <= radius, allowed)
        if path is None:
            raise Reject(f"no path ({self.rec['steps'][i]['kind']})")
        return path

    def _walk(self, path: list) -> None:
        if not self.walker.follow(path, None if "yield" in self.ignore else self.clear):
            raise Reject("blocked by traffic")

    def _look(self, entity: str, limit: float) -> None:
        end = self.walker.t + limit
        while True:
            e = self.walker.vehicle_at(entity, self.walker.t + K.DT)
            if self.walker.sees((e[0], e[1])):
                self.walker.tick(gaze=geo.heading(self.walker.p, (e[0], e[1])))
                return
            if self.walker.t >= end:
                raise Reject("the vehicle to look at is not visible")
            self.walker.tick()

    def step(self, i: int) -> None:
        s, wk = self.rec["steps"][i], self.walker
        first = len(wk.samples) - 1
        k = s["kind"]
        if self.idle:
            wk.wait(self.idle)
        if self.skip != i:
            if k in ("reach", "reach_within", "stay", "either"):
                places = [self.w.point(p) for p in ([s["place"]] if "place" in s else s["places"])]
                paths = []
                for p in places:
                    try:
                        paths.append(self.go(i, p, R_PLACE - 0.4, road=bool(s.get("on_road"))))
                    except Reject as ex:
                        err = ex
                if not paths:
                    raise err
                self._walk(min(paths, key=geo.polyline_length))
                if k == "stay":
                    wk.wait(0.4 if "stay" in self.ignore else s["seconds"] + 0.6)
            elif k == "wait":
                near = self.w.side(s["crossing"], s["side"])
                self._walk(self.go(i, near, R_SIDE - 0.5))
                sig = self.w.signal_name(s["crossing"])
                if "wait" not in self.ignore:
                    self._await_green(sig)
            elif k == "cross":
                self._cross(i, s)
            else:
                if "look" not in self.ignore:
                    self._look(s["entity"], LOOK_S - 0.4)
        wk.wait(0.4)
        self.segments[i] = (first, len(wk.samples) - 1)

    def _await_green(self, signal: str) -> None:
        wk, cycle = self.walker, self.walker.cycles[signal]
        end = wk.t + 80
        while not (K.signal_state(cycle, wk.t) == "green" and K.signal_state(cycle, wk.t + 2.0) == "green"):
            if wk.t > end:
                raise Reject("green never comes")
            wk.tick()

    def _cross(self, i: int, s: dict) -> None:
        wk = self.walker
        near = self.w.side(s["crossing"], s["side"])
        far = self.w.side(s["crossing"], "end" if s["side"] == "start" else "start")
        rules = {r["kind"] for r in self.rec["rules"]} - self.ignore
        if geo.dist(wk.p, near) > R_SIDE:
            self._walk(self.go(i, near, R_SIDE - 0.5))
        if "look_before_road" in rules:
            self._look(self.rec["vehicles"][0]["name"], 30.0)
        if "obey_signal" in rules:
            self._await_green(self.w.signal_name(s["crossing"]))
        self._walk(self.go(i, far, R_SIDE - 0.5, crossing=s["crossing"]))

    def run(self) -> "Plan":
        n = len(self.rec["steps"])
        order = self.order or list(range(n))
        if self.rec["order"] == "any" and self.order is None:       # nearest first
            left, order, here = list(range(n)), [], tuple(self.rec["start"])
            while left:
                def where(j):
                    s = self.rec["steps"][j]
                    return min((self.w.point(p) for p in ([s["place"]] if "place" in s else s["places"])), key=lambda q: geo.dist(here, q))
                j = min(left, key=lambda j: geo.dist(here, where(j)))
                here = where(j)
                order.append(j)
                left.remove(j)
        for i in order:
            self.step(i)
        return self

    def results(self, spec: Optional[dict] = None) -> list:
        """Per task (goal margin, lowest rule margin) as the player would judge it while the task runs."""
        out = []
        samples = self.walker.samples
        for i, t in enumerate((spec or self.spec)["tasks"]):
            if self.rec["order"] == "any":
                seg = samples
            else:
                a, b = self.segments[i]
                seg = samples[a:b + 1]
            goal = K.evaluate(t["goal"], seg)
            rules = [K.evaluate(f, seg) for f in t["safety"]]
            out.append((goal, rules, seg))
        return out


def passes(results: list) -> list:
    return [g[0] >= 0 and all(hi >= 0 for _, hi in rules) for g, rules, _ in results]


# ------------------------------------------------------------------ validation of a record
def _choose_avoid(rec: dict, w: Window, spec: dict, rng: random.Random) -> None:
    """A place next to the unrestricted walk, so that avoiding it matters."""
    free = Plan(rec, w, spec, ignore={"avoid_area"}).run()
    trace = [(s.x, s.y) for s in free.walker.samples]
    used = [w.point(p) for s in rec["steps"] for p in ([s["place"]] if "place" in s else s.get("places", []))]
    used += [tuple(rec["start"])]
    used += [w.side(s["crossing"], side) for s in rec["steps"] if "crossing" in s for side in ("start", "end")]
    options = [o["id"] for o in w.window["elements"]["objects"]]
    options += [_r(p) for p in rng.sample(trace, min(25, len(trace)))]
    rng.shuffle(options)
    for place in options:
        p = w.point(place)
        if max(map(abs, p)) > W.H - 0.5 or any(geo.dist(p, q) < AVOID_R + R_PLACE + 0.6 for q in used):
            continue
        if min(geo.dist(p, q) for q in trace) > AVOID_R + 0.3 or w.grid.surface_at(p) in ("building", "water"):
            continue
        rec["rules"][[r["kind"] for r in rec["rules"]].index("avoid_area")]["place"] = place
        return
    raise Reject("no area to avoid next to the walk")


def _set_time_limits(rec: dict, w: Window, spec: dict) -> None:
    """'Within T seconds': T from the time the reference walk needs, with half as much again."""
    plan = Plan(rec, w, spec).run()
    for i, s in enumerate(rec["steps"]):
        if s["kind"] != "reach_within":
            continue
        a, b = plan.segments[i]
        target = w.point(s["place"])
        a0 = 0 if rec["order"] == "any" else a
        hit = next((k for k in range(a0, b + 1) if geo.dist((plan.walker.samples[k].x, plan.walker.samples[k].y), target) <= R_PLACE), None)
        if hit is None:
            raise Reject("time limit target not reached")
        need = (hit - a0) * K.DT
        s["seconds"] = int(5 * math.ceil((need * 1.5 + 3) / 5))
        if s["seconds"] > MAX_TASK_S:
            raise Reject("time limit above the task limit")


def validate(rec: dict, w: Window, rng: random.Random) -> dict:
    """Completes the open fields of ``rec`` and proves it. Returns facts about the reference walk; raises ``Reject``."""
    for s in rec["steps"]:
        if s["kind"] == "reach_within" and s["seconds"] is None:
            s["seconds"] = MAX_TASK_S
    avoid = next((r for r in rec["rules"] if r["kind"] == "avoid_area"), None)
    if avoid is not None:
        avoid["place"] = list(rec["start"])             # placeholder to build the document once
        spec, _ = scene.check(document(rec, w), w.M)
        avoid["place"] = None
        _choose_avoid(rec, w, spec, rng)
    spec, errors = scene.check(document(rec, w), w.M)
    if any(s["kind"] == "reach_within" for s in rec["steps"]):
        _set_time_limits(rec, w, spec)
        spec, errors = scene.check(document(rec, w), w.M)
    if errors:
        raise Reject("map check: " + errors[0].split(":")[0])
    for v in rec["vehicles"]:                           # moving vehicles stay on their stated road near the meeting place
        e = next(x for x in spec["entities"] if x["name"] == v["name"])
        if v["moving"]:
            route = [(e["start"]["x"], e["start"]["y"])] + [(p["x"], p["y"]) for p in e["route"]]
            if len(route) < 2 or geo.dist_to_polyline(route, w.point(v["meet"])) > 5.0:
                raise Reject("vehicle route misses the meeting place")
        elif w.grid.surface_at((e["start"]["x"], e["start"]["y"])) != "road":
            raise Reject("parked vehicle off the road")
        else:                                           # the whole body: no building under it, not parked on a crossing
            x, y, h, length, width = K.build_movers(spec)[v["name"]].at(0.0)
            body = [(x + a * length * math.cos(h) - b * width * math.sin(h), y + a * length * math.sin(h) + b * width * math.cos(h))
                    for a in (-0.5, -0.25, 0.0, 0.25, 0.5) for b in (-0.5, 0.0, 0.5)]
            if any(w.grid.surface_at(q) in ("building", "water", "crosswalk") for q in body):
                raise Reject("parked vehicle overlaps a building or crossing")

    plan = Plan(rec, w, spec).run()
    res = plan.results()
    for i, (goal, rules, seg) in enumerate(res):
        if goal[0] < 0:
            raise Reject(f"walk misses goal ({rec['steps'][i]['kind']})")
        for j, (_, hi) in enumerate(rules):
            if hi < 0:
                raise Reject(f"walk breaks a rule ({F.describe(spec['tasks'][i]['safety'][j])[:40]})")
        if K.evaluate(spec["tasks"][i]["goal"], seg[:1])[0] >= 0:
            raise Reject(f"task already satisfied at its start ({rec['steps'][i]['kind']})")
        a, b = plan.segments[i]
        if (b - (0 if rec["order"] == "any" else a)) * K.DT > MAX_TASK_S:
            raise Reject("walk longer than the time limit")
    if plan.walker.min_vehicle < COLLISION_D:
        raise Reject("walk touches a vehicle")
    if any(max(abs(s.x), abs(s.y)) > W.H for s in plan.walker.samples):
        raise Reject("walk leaves the window")

    # the specification must reject walks that leave out work
    for i, s in enumerate(rec["steps"]):
        try:
            other = Plan(rec, w, spec, skip=i).run()
        except Reject:
            continue
        if passes(other.results())[i] and s["kind"] != "look":
            raise Reject(f"task passes without its own work ({s['kind']})")
    facts = {"seconds": round(plan.walker.t, 1), "path_m": round(geo.polyline_length([(s.x, s.y) for s in plan.walker.samples]), 1),
             "min_vehicle_m": None if not rec["vehicles"] else round(plan.walker.min_vehicle, 2), "matters": []}
    for kind in ("avoid_area", "obey_signal", "keep_distance", "near_line", "stay_on_sidewalk", "look_before_road"):
        if not any(r["kind"] == kind for r in rec["rules"]):
            continue
        try:
            ign = {kind} | ({"yield"} if kind == "keep_distance" else set())
            other = Plan(rec, w, spec, ignore=ign).run()
            if not all(passes(other.results())):
                facts["matters"].append(kind)           # a walker who ignores the rule fails here
        except Reject:
            pass
    return {"spec": spec, "plan": plan, "facts": facts}


# ------------------------------------------------------------------ request wording (every variant states every field)
SAY = {
    "start": ["Start at {at}.", "The participant starts at {at}.", "Place the walker at {at} at the beginning.", "Begin at {at}.",
              "The starting position is {at}.", "The walk begins at {at}."],
    "signal": ["The pedestrian signal of {c} shows green for {g} s and red for {r} s, starting {i}.",
               "{c} has a pedestrian light: {g} s green, {r} s red, {i} at the start.",
               "Set the light at {c} to a cycle of {g} s green and {r} s red that begins on {i}.",
               "At {c} the signal alternates {g} s of green with {r} s of red and is {i} first."],
    "moving": ["A moving {t} ({n}) drives along {roads} toward {m} at {v} m/s.",
               "{n}, a {t}, comes toward {m} along {roads} with a speed of {v} m/s.",
               "Add a {t} called {n} that approaches {m} at {v} m/s, driving along {roads}.",
               "There is traffic: the {t} {n} heads for {m} via {roads} at {v} m/s."],
    "parked": ["A parked {t} ({n}) stands at {at}.", "{n}, a {t}, is parked at {at}.", "Put a parked {t} named {n} at {at}.",
               "At {at} there is a parked {t}, {n}."],
    "reach": ["walk to {p}", "go to {p}", "reach {p}", "head over to {p}", "make your way to {p}"],
    "reach_within": ["reach {p} within {s} seconds", "get to {p} in at most {s} seconds", "arrive at {p} no later than {s} s after starting this task",
                     "make it to {p} within {s} s"],
    "stay": ["go to {p} and stay there for {s} seconds", "walk to {p} and wait there {s} seconds", "reach {p} and remain there for {s} seconds",
             "stand at {p} for {s} seconds without leaving"],
    "either": ["go to either {a} or {b}", "walk to {a} or to {b}, whichever you like", "reach one of these two: {a} or {b}"],
    "look": ["look at {e}", "check {e} with a look", "turn your eyes to {e}", "glance at {e}"],
    "wait": ["wait for green at {c} on the side at {at}", "stand at the side {at} of {c} until its light turns green",
             "at the {at} side of {c}, wait until the signal shows green"],
    "cross": ["cross {c} from the side at {at}", "get across {c}, starting from the side at {at}", "walk over {c} beginning on its side at {at}",
              "use {c} to cross the road, from the side at {at}"],
    "one": ["Task: {x}.", "The participant has to {x}.", "Goal: {x}.", "What to do: {x}."],
    "sequence": (["Tasks, in this order: {x}.", "Do the following one after another: {x}.", "In sequence: {x}."], ["; then ", "; after that ", "; next "]),
    "ordered": (["Tasks in strict order, and no later place may be visited before its turn: {x}.",
                 "Do these one after another and do not set foot at a later target early: {x}.",
                 "Strictly in this order (visiting a later place too soon is a failure): {x}."], ["; then ", "; after that ", "; next "]),
    "any": (["Tasks, in any order: {x}.", "Do all of these, in whichever order: {x}.", "Complete each of the following; the order is free: {x}."],
            ["; ", "; and also "]),
    "collide": ["Do not collide with {e}.", "Avoid any collision with {e}.", "Touching {e} means failure."],
    "distance": ["Stay at least {d} m away from {e}.", "Keep a distance of {d} m or more to {e}.", "Never come closer than {d} m to {e}."],
    "avoid_area": ["Do not go near {p}.", "Stay away from {p} the whole time.", "Avoid the area around {p}.", "Keep out of the surroundings of {p}."],
    "stay_on_sidewalk": ["Stay on the sidewalk.", "Do not leave the sidewalk.", "Walk on the sidewalk only."],
    "near_line": ["Stay within {w} m of the line through {pts}.", "Never stray more than {w} m from the line running through {pts}.",
                  "Keep to a margin of {w} m around the line through {pts}."],
    "obey_signal": ["Do not step onto {c} unless the signal is green.", "Entering {c} on red counts as a failure.", "Only enter {c} while its light is green."],
    "look_before_road": ["Do not step onto the road before looking at {e}.", "Look at {e} before you set foot on the road.",
                         "The road is off limits until you have looked at {e}."],
}


def request(rec: dict, w: Window, rng: random.Random) -> str:
    def say(key, **kw):
        return rng.choice(SAY[key]).format(**kw)

    def place(p, on_road=False):
        if on_road:
            return rng.choice([f"the point {_at(p)} on the road", f"the spot {_at(p)} on the carriageway"])
        return p if isinstance(p, str) else rng.choice([f"the point {_at(p)}", f"the spot {_at(p)}", f"position {_at(p)}"])

    scene_parts = []
    sig = rec["signal"]
    if sig:
        scene_parts.append(say("signal", c=sig["crossing"], g=sig["green"], r=sig["red"], i=sig["initial"]))
    for v in rec["vehicles"]:
        if v["moving"]:
            meet = v["meet"] if isinstance(v["meet"], str) else f"the point {_at(v['meet'])}"
            scene_parts.append(say("moving", t=v["type"], n=v["name"], roads=" and then ".join(v["roads"]), m=meet, v=v["speed"]))
        else:
            scene_parts.append(say("parked", t=v["type"], n=v["name"], at=_at(v["at"])))
    texts = []
    for s in rec["steps"]:
        k = s["kind"]
        if k in ("reach", "reach_within", "stay"):
            texts.append(say(k, p=place(s["place"], s.get("on_road")), s=s.get("seconds")))
        elif k == "either":
            texts.append(say(k, a=place(s["places"][0]), b=place(s["places"][1])))
        elif k == "look":
            texts.append(say(k, e=s["entity"]))
        else:
            texts.append(say(k, c=s["crossing"], at=_at(w.side(s["crossing"], s["side"]))))
    if rec["order"] == "one":
        task = say("one", x=texts[0])
    else:
        heads, joins = SAY[rec["order"]]
        joined = texts[0]
        for t in texts[1:]:
            joined += rng.choice(joins) + t
        task = rng.choice(heads).format(x=joined)
    rules = []
    for r in rec["rules"]:
        k = r["kind"]
        if k == "keep_distance":
            for v in rec["vehicles"]:
                rules.append(say("collide", e=v["name"]) if r["d"] == COLLISION_D else say("distance", d=r["d"], e=v["name"]))
        elif k == "avoid_area":
            rules.append(say(k, p=place(r["place"])))
        elif k == "near_line":
            rules.append(say(k, w=r["width"], pts=", ".join(_at(p) for p in r["path"])))
        elif k == "obey_signal":
            rules.append(say(k, c=rec["signal"]["crossing"]))
        elif k == "look_before_road":
            rules.append(say(k, e=rec["vehicles"][0]["name"]))
        else:
            rules.append(say(k))
    rng.shuffle(rules)
    start = say("start", at=_at(rec["start"]))
    layouts = [[start] + scene_parts + [task] + rules, [start, task] + scene_parts + rules, scene_parts + [start, task] + rules,
               [start] + scene_parts + rules + [task]]
    return " ".join(rng.choices(layouts, [5, 2, 2, 1])[0])


def kind_of(rec: dict) -> str:
    vehicle = "moving" if any(v["moving"] for v in rec["vehicles"]) else "parked" if rec["vehicles"] else "none"
    return "|".join(["+".join(s["kind"] for s in rec["steps"]), rec["order"], "+".join(r["kind"] for r in rec["rules"]) or "-", vehicle])


def reply(rec: dict, w: Window, rng: Optional[random.Random] = None) -> str:
    models = {v["name"]: (rng.choice(MODELS[v["type"]]) if rng else MODELS[v["type"]][0]) for v in rec["vehicles"]}
    return "```json\n" + json.dumps(document(rec, w, models), separators=(",", ":")) + "\n```"


# ------------------------------------------------------------------ judging a reply
def parse(text: str) -> Optional[dict]:
    body = text.strip()
    if "```" in body:
        body = body.split("```json", 1)[-1] if "```json" in body else body.split("```", 1)[-1]
        body = body.split("```", 1)[0]
    try:
        doc = json.loads(body)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _same(a, b) -> bool:
    """Equal formulas: and/or in any order, positions may differ by POSITION_TOL."""
    if isinstance(a, dict) and isinstance(b, dict):
        keys = (set(a) | set(b)) - {"label"}
        if a.get("kind") == "disc" and b.get("kind") == "disc":
            return geo.dist((a["x"], a["y"]), (b["x"], b["y"])) <= POSITION_TOL and abs(a["r"] - b["r"]) < 0.05
        if a.get("op") == b.get("op") and a.get("op") in ("and", "or"):
            x, y = a["args"], b["args"]
            return len(x) == len(y) and any(all(map(_same, x, p)) for p in permutations(y))
        if "path" in a and "path" in b:
            if len(a["path"]) != len(b["path"]) or any(geo.dist(p, q) > POSITION_TOL for p, q in zip(a["path"], b["path"])):
                return False
            keys -= {"path"}
        return all(_same(a.get(k), b.get(k)) for k in keys)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_same, a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) < 0.05
    return a == b


def _leaves(f: dict) -> list:
    """Predicates and time bounds of a formula, for the test that two differently written formulas use the same numbers."""
    out = []
    for n in F.walk(f):
        if n["op"] in F.ATOMS:
            out.append(n)
        elif n["op"] in ("eventually", "always", "until") and n.get("end") is not None:
            out.append({"op": "bound", "start": n.get("start", 0), "end": n["end"]})
    unique: list = []
    for x in out:
        if not any(_same(x, y) for y in unique):
            unique.append(x)
    return unique


def _walks(rec: dict, w: Window, spec: dict) -> list:
    """The reference walk and walks that each break one thing."""
    n = len(rec["steps"])
    flags = [{}] + [{"skip": i} for i in range(n)] + [{"ignore": {k}} for k in
                                                      ("wait", "stay", "look", "avoid_area", "near_line", "stay_on_sidewalk", "look_before_road", "obey_signal", "order")]
    flags += [{"ignore": {"keep_distance", "yield"}}, {"idle": 6.0}, {"idle": 16.0}]
    flags += [{"order": list(p)} for p in permutations(range(n)) if list(p) != list(range(n))]
    out = []
    for f in flags:
        if "order" in f and rec["order"] != "any" and any(s["kind"] in ("cross", "wait") for s in rec["steps"]):
            continue
        try:
            out.append(Plan(rec, w, spec, **f).run())
        except (Reject, KeyError):
            continue
    return out


def verify(rec: dict, w: Window, text: str) -> dict:
    """{'ok', 'fields': {field: bool}, 'parts': {goals, rules: share right}, 'error'} ('parts' only for a reply that builds). Formulas count as right if written identically (up to and/or order), or if they use
    the same predicates and time bounds and agree on every test walk."""
    doc = parse(text)
    if doc is None:
        return {"ok": False, "fields": {}, "error": "reply is not one JSON document"}
    try:
        spec, errors = scene.check(doc, w.M)
        ref_doc = document(rec, w)
        ref, _ = scene.check(ref_doc, w.M)
    except (F.SpecError, ValueError, KeyError, TypeError, AttributeError) as ex:
        return {"ok": False, "fields": {}, "error": f"{type(ex).__name__}: {str(ex)[:300]}"}
    fields: dict = {"map": not errors}
    user = next(e for e in spec["entities"] if e["role"] == "user")
    fields["start"] = geo.dist((user["start"]["x"], user["start"]["y"]), rec["start"]) <= POSITION_TOL

    got = {e["name"]: e for e in spec["entities"] if e["role"] != "user"}
    raw = {v.get("name"): v for v in doc.get("vehicles", [])}
    ok = set(got) == {v["name"] for v in rec["vehicles"]}
    for v in rec["vehicles"]:
        e = got.get(v["name"])
        if e is None:
            continue
        ok &= e["model"] in MODELS[v["type"]] and bool(e["moving"]) == v["moving"]
        if v["moving"]:
            meet = raw[v["name"]].get("meet")
            ok &= raw[v["name"]].get("roads") == v["roads"] and abs(e["speed"] - v["speed"]) < 0.05
            ok &= meet == v["meet"] if isinstance(v["meet"], str) else \
                isinstance(meet, list) and geo.dist(meet, v["meet"]) <= POSITION_TOL
        else:
            ok &= geo.dist((e["start"]["x"], e["start"]["y"]), v["at"]) <= POSITION_TOL
    fields["vehicles"] = bool(ok)
    key = lambda c: (c["signal"], c["green"], c["red"], c["initial"], c["offset"])  # noqa: E731
    fields["signal"] = sorted(map(key, spec["signals"])) == sorted(map(key, ref["signals"]))
    n = len(rec["steps"])
    fields["task_count"] = len(spec["tasks"]) == n
    fields["time_limits"] = all(t["timeout"]["initial"] == LIMIT and t["timeout"]["baseline"] == BASELINE and not t["start_time"] for t in spec["tasks"])

    def deps(sp):
        ids = [t["id"] for t in sp]
        closure = []
        for t in sp:
            todo, seen = list(t["depends_on"]), set()
            while todo:
                d = todo.pop()
                if d not in seen:
                    seen.add(d)
                    todo += next(x for x in sp if x["id"] == d)["depends_on"]
            closure.append({ids.index(d) for d in seen})
        return closure

    walks: Optional[list] = None

    def equal(mine: dict, want: dict) -> bool:
        nonlocal walks
        if _same(mine, want):
            return True
        a, b = _leaves(mine), _leaves(want)
        if len(a) != len(b) or not all(any(_same(x, y) for y in b) for x in a):
            return False
        if walks is None:
            walks = _walks(rec, w, ref)
        for p in walks:
            segs = [p.walker.samples] + [p.walker.samples[s[0]:s[1] + 1] for s in p.segments.values()]
            for seg in segs:
                x, y = K.evaluate(mine, seg), K.evaluate(want, seg)
                if (x[0] >= 0) != (y[0] >= 0) or (x[1] >= 0) != (y[1] >= 0):
                    return False
        return True

    cache: dict = {}

    def matches(order) -> tuple:
        """(goals right, safety formulas right, safety formulas counted) for reply task order[i] taken as reference task i."""
        goals = right = total = 0
        for i, j in enumerate(order):
            if (i, j) not in cache:
                got, want = spec["tasks"][j]["safety"], ref["tasks"][i]["safety"]
                found = sum(any(equal(g, x) for g in got) for x in want)
                used = sum(any(equal(g, x) for x in want) for g in got)
                cache[i, j] = (equal(spec["tasks"][j]["goal"], ref["tasks"][i]["goal"]), min(found, used), max(len(got), len(want)))
            g, r, t = cache[i, j]
            goals, right, total = goals + g, right + r, total + t
        return goals, right, total

    if not fields["task_count"]:
        free = list(range(len(spec["tasks"])))
        hit = 0
        for i in range(n):
            j = next((j for j in free if equal(spec["tasks"][j]["goal"], ref["tasks"][i]["goal"])), None)
            if j is not None:
                free.remove(j)
                hit += 1
        parts = {"goals": hit / max(n, len(spec["tasks"])), "rules": 0.0}
        fields.update(goals=False, rules=False, order=False)
        return {"ok": False, "fields": fields, "parts": parts, "error": "; ".join(errors)[:300]}

    orders = permutations(range(n)) if rec["order"] == "any" else [tuple(range(n))]
    best = (-1, -1.0)
    for o in orders:
        goals, right, total = matches(o)
        best = max(best, (goals, right / total if total else 1.0))
        if best == (n, 1.0):
            break
    parts = {"goals": best[0] / n, "rules": best[1]}
    fields["goals"] = best[0] == n
    fields["rules"] = fields["goals"] and best[1] == 1.0
    mine = deps(spec["tasks"])
    if rec["order"] == "any":
        fields["order"] = not any(mine) and all(t["mode"] == "parallel" for t in spec["tasks"]) if n > 1 else True
    else:
        fields["order"] = mine == deps(ref["tasks"])
    return {"ok": all(fields.values()), "fields": fields, "parts": parts, "error": "; ".join(errors)[:300]}


# ------------------------------------------------------------------ generation
def make(w: Window, balance: Balance, rng: random.Random, held: bool = False, why: Optional[Counter] = None, tries: int = 12) -> Optional[dict]:
    """One proven record for the window (or None after ``tries`` types)."""
    why = Counter() if why is None else why
    for _ in range(tries):
        t = balance.draw(w.flags, rng, held)
        if t is None:
            continue
        for _attempt in range(3):
            try:
                rec = instantiate(w, t, rng)
                proof = validate(rec, w, rng)
                text = request(rec, w, rng)
                answer = reply(rec, w, rng)
                judged = verify(rec, w, answer)
                if not judged["ok"]:
                    raise Reject("reference fails the verifier: " + (",".join(k for k, v in judged["fields"].items() if not v) or judged["error"][:80]))
            except Reject as ex:
                why[str(ex)] += 1
                continue
            except (ValueError, KeyError) as ex:
                why[f"{type(ex).__name__}: {str(ex)[:90]}"] += 1
                continue
            balance.accept(t)
            return {"kind": kind_of(rec), "record": rec, "request": text, "reply": answer, "facts": proof["facts"], "plan": proof["plan"]}
    return None
