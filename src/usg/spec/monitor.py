"""Quantitative semantics of the specification language: interval robustness over a trajectory prefix.

``Monitor.rho(formula, k)`` returns ``(lo, hi)`` for the formula anchored at sample ``k``:

* ``lo >= 0``  the formula is already SATISFIED whatever the user does next;
* ``hi <  0``  the formula is already VIOLATED whatever the user does next;
* otherwise it is still undecided.

Values are signed margins in the units of the atoms (metres, degrees, m/s; qualitative atoms give +-1). With a COMPLETE
trace (the task has ended) ``lo == hi`` is the usual signal-temporal-logic robustness. The player (TypeScript,
``runtime/monitor.ts``) implements exactly the same rules; ``tests/test_spec.py`` and ``player/tests`` compare them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .. import geo
from .formula import BIG

SURFACE_SETS: dict[str, frozenset] = {
    "walkable": frozenset({"crosswalk", "sidewalk", "path", "ground"}),
    "pedestrian_infra": frozenset({"crosswalk", "sidewalk", "path"}),
    "crosswalk": frozenset({"crosswalk"}),
    "road": frozenset({"road", "crosswalk"}),
    "sidewalk": frozenset({"sidewalk"}),
    "path": frozenset({"path"}),
    "ground": frozenset({"ground"}),
}


@dataclass
class Sample:
    x: float
    y: float
    gaze: float                     # radians, 0 = east, counter-clockwise
    speed: float                    # m/s
    surface: str
    ents: dict = field(default_factory=dict)       # name -> (centre_x, centre_y, heading, length, width)
    signals: dict = field(default_factory=dict)    # signal name -> 'green' | 'red'
    events: frozenset = frozenset()                # storyboard events that have started


def to_local(p, origin, hdg):
    dx, dy = p[0] - origin[0], p[1] - origin[1]
    c, s = math.cos(hdg), math.sin(hdg)
    return (dx * c + dy * s, -dx * s + dy * c)


def dist_to_obb(p, center, hdg, length, width) -> float:
    lx, ly = to_local(p, center, hdg)
    return math.hypot(max(abs(lx) - length / 2, 0.0), max(abs(ly) - width / 2, 0.0))


def atom_value(n: dict, s: Sample) -> float:
    """Signed margin of one atom at one sample."""
    op = n["op"]
    p = (s.x, s.y)
    if op == "true":
        return BIG
    if op == "in_zone":
        z = n["zone"]
        k = z["kind"]
        if k == "disc":
            return z["r"] - math.hypot(s.x - z["x"], s.y - z["y"])
        if k == "rect":
            lx, ly = to_local(p, (z["cx"], z["cy"]), z["h"])
            return min(z["hl"] - abs(lx), z["hw"] - abs(ly))
        e = s.ents.get(z["name"])
        return -BIG if e is None else z["r"] - math.hypot(s.x - e[0], s.y - e[1])
    if op == "on_surface":
        return 1.0 if s.surface in SURFACE_SETS.get(n["surface"], frozenset()) else -1.0
    if op == "near_path":
        return n["tol"] - geo.dist_to_polyline([tuple(q) for q in n["path"]], p)
    if op in ("dist_le", "dist_ge"):
        e = s.ents.get(n["entity"])
        if e is None:
            return -BIG if op == "dist_le" else BIG
        d = dist_to_obb(p, (e[0], e[1]), e[2], e[3], e[4])
        return n["d"] - d if op == "dist_le" else d - n["d"]
    if op == "look_at":
        if "entity" in n:
            e = s.ents.get(n["entity"])
            if e is None:
                return -BIG
            tx, ty = e[0], e[1]
        else:
            tx, ty = n["point"]
        err = abs(geo.wrap_pi(s.gaze - math.atan2(ty - s.y, tx - s.x))) * 180.0 / math.pi
        return n["angle"] - err
    if op == "speed_le":
        return n["v"] - s.speed
    if op == "speed_ge":
        return s.speed - n["v"]
    if op == "signal_is":
        return 1.0 if s.signals.get(n["signal"]) == n["state"] else -1.0
    if op == "event":
        return 1.0 if n["name"] in s.events else -1.0
    raise ValueError(f"not an atom: {op}")


ATOM_OPS = {"true", "in_zone", "on_surface", "near_path", "dist_le", "dist_ge", "look_at", "speed_le", "speed_ge",
            "signal_is", "event"}


class Monitor:
    def __init__(self, samples: list[Sample], dt: float = 0.1, complete: bool = False):
        self.s = samples
        self.dt = dt
        self.complete = complete
        self.K = len(samples) - 1
        self._memo: dict = {}

    # ---- window of sample indices [lo_i, hi_i] for an interval anchored at k
    def _window(self, n: dict, k: int):
        a = float(n.get("start", 0) or 0)
        b = n.get("end")
        ia = int(math.ceil(a / self.dt - 1e-9))
        ib = None if b is None else int(math.floor(float(b) / self.dt + 1e-9))
        first = k + ia
        last_known = self.K if ib is None else min(k + ib, self.K)
        unknown = (not self.complete) and (ib is None or k + ib > self.K)
        return first, last_known, unknown

    def rho(self, n: dict, k: int = 0) -> tuple[float, float]:
        key = (id(n), k)
        r = self._memo.get(key)
        if r is None:
            r = self._rho(n, k)
            self._memo[key] = r
        return r

    def _rho(self, n: dict, k: int) -> tuple[float, float]:
        if k > self.K:
            return (-BIG, BIG) if not self.complete else (-BIG, -BIG)
        op = n["op"]
        if op in ATOM_OPS:
            v = atom_value(n, self.s[k])
            return (v, v)
        if op == "not":
            lo, hi = self.rho(n["arg"], k)
            return (-hi, -lo)
        if op == "and":
            rs = [self.rho(c, k) for c in n["args"]]
            return (min(r[0] for r in rs), min(r[1] for r in rs))
        if op == "or":
            rs = [self.rho(c, k) for c in n["args"]]
            return (max(r[0] for r in rs), max(r[1] for r in rs))
        if op == "implies":
            alo, ahi = self.rho(n["a"], k)
            blo, bhi = self.rho(n["b"], k)
            return (max(-ahi, blo), max(-alo, bhi))
        if op == "prev":
            if k == 0:
                return (BIG, BIG) if n.get("init", True) else (-BIG, -BIG)
            return self.rho(n["arg"], k - 1)
        if op in ("eventually", "always"):
            first, last, unknown = self._window(n, k)
            ev = op == "eventually"
            lo = -BIG if ev else BIG
            hi = -BIG if ev else BIG
            for j in range(first, last + 1):
                l, h = self.rho(n["arg"], j)
                if ev:
                    lo, hi = max(lo, l), max(hi, h)
                else:
                    lo, hi = min(lo, l), min(hi, h)
            if unknown:
                if ev:
                    hi = BIG
                else:
                    lo = -BIG
            return (lo, hi)
        if op == "until":
            first, last, unknown = self._window(n, k)
            lo_best, hi_best = -BIG, -BIG
            ll, lh = BIG, BIG                       # running min of left over [k, j)
            for j in range(k, last + 1):
                if j >= first:
                    rlo, rhi = self.rho(n["right"], j)
                    lo_best = max(lo_best, min(rlo, ll))
                    hi_best = max(hi_best, min(rhi, lh))
                l, h = self.rho(n["left"], j)
                ll, lh = min(ll, l), min(lh, h)
            if unknown:
                hi_best = max(hi_best, lh)          # right might still happen after every known sample
            return (lo_best, hi_best)
        raise ValueError(f"unknown op {op}")


# ------------------------------------------------------------------ task-level status
def goal_status(goal: dict, safety: list[dict], samples: list[Sample], dt: float = 0.1, complete: bool = False) -> dict:
    """{'status': running|success|failed, 'reason', 'goal': (lo,hi), 'safety': [(lo,hi)...]} for one task."""
    m = Monitor(samples, dt, complete)
    g = m.rho(goal, 0)
    sf = [m.rho(f, 0) for f in safety]
    bad = next((i for i, (lo, hi) in enumerate(sf) if hi < 0), None)
    if bad is not None:
        return {"status": "failed", "reason": f"safety {bad}", "goal": g, "safety": sf}
    if g[0] >= 0:
        return {"status": "success", "reason": "ok", "goal": g, "safety": sf}
    if g[1] < 0:
        return {"status": "failed", "reason": "goal", "goal": g, "safety": sf}
    return {"status": "running", "reason": "", "goal": g, "safety": sf}
