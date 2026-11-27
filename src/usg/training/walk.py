"""Path search on a map window and timed reference walks.

The window is a 0.5 m grid. A cell is usable if its surface is walkable (the road only where the task allows it); steps through
barriers are forbidden. ``Walker`` turns found paths into the samples the specification monitor evaluates.
"""
from __future__ import annotations

import heapq
import math
from typing import Callable, Optional

from .. import geo
from ..spec.monitor import Monitor, Sample, dist_to_obb
from ..spec.oracle import build_movers, signal_state
from . import window as W

RES = 0.5
N = int(round(W.SIZE / RES))
SPEED = 1.2
DT = 0.2
FREE = ("sidewalk", "path", "ground")
Cell = tuple


def xy(c: Cell) -> tuple:
    return (-W.H + (c[0] + 0.5) * RES, -W.H + (c[1] + 0.5) * RES)


def cell(p) -> Cell:
    return (min(N - 1, max(0, int((p[0] + W.H) / RES))), min(N - 1, max(0, int((p[1] + W.H) / RES))))


def _cross(a, b, c, d) -> bool:
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return side(a, b, c) * side(a, b, d) <= 0 and side(c, d, a) * side(c, d, b) < 0


def in_rect(p, z: dict, margin: float = 0.0) -> bool:
    dx, dy = p[0] - z["cx"], p[1] - z["cy"]
    c, s = math.cos(z["h"]), math.sin(z["h"])
    return abs(dx * c + dy * s) <= z["hl"] + margin and abs(-dx * s + dy * c) <= z["hw"] + margin


class Grid:
    def __init__(self, window: dict, model):
        self.model = model
        self._surface: dict = {}
        self.surface = {(i, j): model.surface_at(xy((i, j))) for i in range(N) for j in range(N)}
        # sidewalk that the map TEXT also lists (the simulator map keeps strips the window cleaning cut away)
        strips = [(o["line"], o["width"] / 2 + 0.05) for o in window["elements"]["sidewalks"]]
        self.sidewalk = {c for c, s in self.surface.items() if s == "sidewalk" and any(geo.dist_to_polyline(q, xy(c)) <= r for q, r in strips)}
        walls = [(p, q) for o in window["elements"]["barriers"] for p, q in zip(o["line"], o["line"][1:])]
        self.blocked: set = set()                       # steps that cross a barrier
        for p, q in walls:
            i0, j0 = cell((min(p[0], q[0]) - 1, min(p[1], q[1]) - 1))
            i1, j1 = cell((max(p[0], q[0]) + 1, max(p[1], q[1]) + 1))
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    for di, dj in ((1, 0), (0, 1), (1, 1), (1, -1)):
                        b = (i + di, j + dj)
                        if b in self.surface and _cross(xy((i, j)), xy(b), p, q):
                            self.blocked.add(((i, j), b))
                            self.blocked.add((b, (i, j)))

    def surface_at(self, p) -> str:
        key = (round(p[0] * 10), round(p[1] * 10))
        s = self._surface.get(key)
        if s is None:
            s = self._surface[key] = self.model.surface_at((key[0] / 10, key[1] / 10))
        return s

    def search(self, start, allowed: Callable[[Cell], bool], goal: Optional[Callable] = None) -> tuple[dict, Optional[Cell]]:
        """Dijkstra from the point ``start``. Returns (tree: cell -> (cost, parent), first cell satisfying ``goal``)."""
        s = cell(start)
        tree: dict = {s: (0.0, None)}
        heap = [(0.0, s)]
        done: set = set()
        while heap:
            d, a = heapq.heappop(heap)
            if a in done:
                continue
            done.add(a)
            if goal is not None and goal(xy(a)) and (a == s or allowed(a)):
                return tree, a
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                b = (a[0] + di, a[1] + dj)
                if b not in self.surface or (a, b) in self.blocked or not allowed(b):
                    continue
                if di and dj and not (allowed((a[0] + di, a[1])) and allowed((a[0], a[1] + dj))):
                    continue
                step = RES * math.hypot(di, dj) * (1.4 if self.surface[b] == "ground" else 1.0)     # prefer sidewalks and paths
                if b not in tree or d + step < tree[b][0]:
                    tree[b] = (d + step, a)
                    heapq.heappush(heap, (d + step, b))
        return tree, None

    def path(self, start, goal: Callable, allowed: Callable[[Cell], bool]) -> Optional[list]:
        """Points from ``start`` to the nearest point satisfying ``goal``, or None if there is no way."""
        tree, end = self.search(start, allowed, goal)
        if end is None:
            return None
        out = []
        while end is not None:
            out.append(xy(end))
            end = tree[end][1]
        return [tuple(start)] + out[::-1][1:]


class Walker:
    """A walker producing monitor samples; time runs from the start of the scenario."""

    def __init__(self, grid: Grid, spec: dict):
        self.grid = grid
        user = next(e for e in spec["entities"] if e["role"] == "user")
        self.p = (user["start"]["x"], user["start"]["y"])
        self.gaze = user["start"]["h"]
        self.t = 0.0
        self.movers = build_movers(spec)
        self.cycles = {c["signal"]: c for c in spec["signals"]}
        self.samples: list[Sample] = []
        self.min_vehicle = 1e9
        self._snap(0.0)

    def vehicle_at(self, name: str, t: Optional[float] = None) -> tuple:
        return self.movers[name].at(self.t if t is None else t)

    def _snap(self, speed: float) -> None:
        ents = {n: m.at(self.t) for n, m in self.movers.items()}
        for e in ents.values():
            self.min_vehicle = min(self.min_vehicle, dist_to_obb(self.p, (e[0], e[1]), e[2], e[3], e[4]))
        signals = {s: signal_state(c, self.t) for s, c in self.cycles.items()}
        self.samples.append(Sample(self.p[0], self.p[1], self.gaze, speed, self.grid.surface_at(self.p), ents, signals, frozenset()))

    def tick(self, p=None, gaze: Optional[float] = None) -> None:
        self.t += DT
        speed = 0.0
        if p is not None:
            speed = geo.dist(self.p, p) / DT
            if speed > 1e-6:
                self.gaze = geo.heading(self.p, p)
            self.p = p
        if gaze is not None:
            self.gaze = gaze
        self._snap(speed)

    def wait(self, seconds: float) -> None:
        end = self.t + seconds - 1e-9
        while self.t < end:
            self.tick()

    def _threat(self, p, clear: float) -> bool:
        for m in self.movers.values():
            if not m.e["moving"]:
                continue
            for ahead in (0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.5, 3.0):
                e = m.at(self.t + ahead)
                if dist_to_obb(p, (e[0], e[1]), e[2], e[3], e[4]) < clear:
                    return True
        return False

    def follow(self, points: list, clear: Optional[float] = 0.8, limit: float = 150.0) -> bool:
        """Walk along ``points``. With ``clear`` the walker waits before coming that close to a moving vehicle."""
        end = self.t + limit
        for q in points[1:]:
            while geo.dist(self.p, q) > 1e-6:
                if self.t > end:
                    return False
                step = min(SPEED * DT, geo.dist(self.p, q))
                h = geo.heading(self.p, q)
                n = (self.p[0] + math.cos(h) * step, self.p[1] + math.sin(h) * step)
                # wait only before ENTERING the vehicle's way; once inside, walk on and leave it
                if clear is not None and self._threat(n, clear) and not self._threat(self.p, clear):
                    self.tick()
                    continue
                self.tick(n)
        return True

    def sees(self, target) -> bool:
        """No building between the walker and the target."""
        pts = W.samples([self.p, target], 1.0)
        return geo.dist(self.p, target) <= 80.0 and all(self.grid.surface_at(q) != "building" for q in pts[:-1])


def evaluate(formula: dict, samples: list) -> tuple[float, float]:
    """(lo, hi) robustness while the task is running: lo >= 0 already satisfied, hi < 0 already violated."""
    return Monitor(samples, DT, complete=False).rho(formula, 0)
