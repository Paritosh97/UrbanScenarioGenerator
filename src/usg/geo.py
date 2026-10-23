"""Single source of truth for coordinates.

Everything (3D geometry, OpenDRIVE, scenario positions, LLM context) uses ONE
local East-North-Up frame in metres, anchored at ``Projection.origin``. The map
is projected exactly once (in ``usg.mapmodel.build_map``) and every exporter
reads the already-projected metric data, so the 3D scene, the road network and
the scenario can never drift apart.
"""
from __future__ import annotations

import math
from typing import Sequence

R_EARTH = 6378137.0

Pt = tuple[float, float]


class Projection:
    """Local tangent-plane projection (x=east, y=north) around (lat0, lon0).

    Error against a true transverse Mercator is ~1e-9 relative at city scale.
    """

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self._k = math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> Pt:
        return (R_EARTH * math.radians(lon - self.lon0) * self._k,
                R_EARTH * math.radians(lat - self.lat0))

    def to_latlon(self, x: float, y: float) -> Pt:
        return (self.lat0 + math.degrees(y / R_EARTH),
                self.lon0 + math.degrees(x / (R_EARTH * self._k)))

    def to_dict(self) -> dict:
        return {"lat": self.lat0, "lon": self.lon0}

    @staticmethod
    def from_dict(d: dict) -> "Projection":
        return Projection(d["lat"], d["lon"])


# ---------------------------------------------------------------- vectors
def dist(a: Pt, b: Pt) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def heading(a: Pt, b: Pt) -> float:
    """Radians, 0 = +x (east), counter-clockwise (OpenDRIVE/OpenSCENARIO convention)."""
    return math.atan2(b[1] - a[1], b[0] - a[0])


def wrap_pi(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def polyline_length(pts: Sequence[Pt]) -> float:
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def cumulative(pts: Sequence[Pt]) -> list[float]:
    out, s = [0.0], 0.0
    for i in range(len(pts) - 1):
        s += dist(pts[i], pts[i + 1])
        out.append(s)
    return out


def point_at(pts: Sequence[Pt], s: float) -> tuple[Pt, float]:
    """Point and heading at arc length ``s`` (clamped)."""
    cum = cumulative(pts)
    s = max(0.0, min(s, cum[-1]))
    for i in range(len(pts) - 1):
        if s <= cum[i + 1] or i == len(pts) - 2:
            seg = cum[i + 1] - cum[i]
            f = 0.0 if seg < 1e-9 else (s - cum[i]) / seg
            a, b = pts[i], pts[i + 1]
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), heading(a, b)
    return pts[-1], 0.0


def project_to_polyline(pts: Sequence[Pt], p: Pt) -> tuple[float, float, Pt, float]:
    """Closest point on polyline. Returns (s, t, closest, heading); t>0 is LEFT of travel."""
    best = (1e18, 0.0, 0.0, pts[0], 0.0)
    acc = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        seg = math.sqrt(l2)
        f = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
        c = (a[0] + dx * f, a[1] + dy * f)
        d = dist(c, p)
        if d < best[0]:
            cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0])
            t = d if cross >= 0 else -d
            best = (d, acc + seg * f, t, c, math.atan2(dy, dx))
        acc += seg
    return best[1], best[2], best[3], best[4]


def dist_to_polyline(pts: Sequence[Pt], p: Pt) -> float:
    return abs(project_to_polyline(pts, p)[1])


def sub_polyline(pts: Sequence[Pt], s0: float, s1: float) -> list[Pt]:
    cum = cumulative(pts)
    s0, s1 = max(0.0, s0), min(cum[-1], s1)
    if s1 <= s0:
        return [point_at(pts, s0)[0]]
    out = [point_at(pts, s0)[0]]
    for i in range(1, len(pts) - 1):
        if s0 < cum[i] < s1:
            out.append(pts[i])
    out.append(point_at(pts, s1)[0])
    return out


def offset_polyline(pts: Sequence[Pt], d: float, miter_limit: float = 2.0) -> list[Pt]:
    """Offset to the LEFT by ``d`` (negative = right) with clamped mitres."""
    n = len(pts)
    if n < 2:
        return list(pts)
    normals = []
    for i in range(n - 1):
        h = heading(pts[i], pts[i + 1])
        normals.append((-math.sin(h), math.cos(h)))
    out = []
    for i in range(n):
        if i == 0:
            nx, ny = normals[0]
            k = 1.0
        elif i == n - 1:
            nx, ny = normals[-1]
            k = 1.0
        else:
            ax, ay = normals[i - 1]
            bx, by = normals[i]
            mx, my = ax + bx, ay + by
            ml = math.hypot(mx, my)
            if ml < 1e-9:
                nx, ny, k = ax, ay, 1.0
            else:
                nx, ny = mx / ml, my / ml
                k = min(miter_limit, 1.0 / max(1e-3, nx * ax + ny * ay))
        out.append((pts[i][0] + nx * d * k, pts[i][1] + ny * d * k))
    return out


def resample(pts: Sequence[Pt], step: float) -> list[Pt]:
    total = polyline_length(pts)
    if total < 1e-6:
        return list(pts)
    n = max(1, int(math.ceil(total / step)))
    return [point_at(pts, total * i / n)[0] for i in range(n + 1)]


def point_in_polygon(poly: Sequence[Pt], p: Pt) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-18) + xi:
            inside = not inside
        j = i
    return inside


def polygon_area(poly: Sequence[Pt]) -> float:
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def polygon_centroid(poly: Sequence[Pt]) -> Pt:
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
