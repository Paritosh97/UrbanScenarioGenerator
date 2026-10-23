"""Metric map model: the single scene description shared by the web renderer, OpenDRIVE and the LLM.

``build_map`` (osm -> MapModel) projects once. Everything downstream consumes the
metric ``MapModel`` (or its JSON form, ``scene_map.json``).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from . import geo
from .geo import Pt

LANE_W = 3.25
DEFAULT_SIDEWALK_W = 2.0
CAR_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
               "residential", "living_street", "service", "motorway_link", "trunk_link",
               "primary_link", "secondary_link", "tertiary_link"}
SIDEWALK_DEFAULT_CLASSES = {"primary", "secondary", "tertiary", "unclassified",
                            "residential", "living_street", "primary_link",
                            "secondary_link", "tertiary_link"}
SPEED_DEFAULT = {"motorway": 33.0, "trunk": 25.0, "primary": 13.9, "secondary": 13.9,
                 "tertiary": 13.9, "residential": 8.3, "living_street": 4.2, "service": 5.5}

# Surfaces the runtime/validator reason about. Same names are used by the web runtime.
SURFACES = ("road", "crosswalk", "sidewalk", "path", "building", "water", "ground")
WALKABLE = {"crosswalk", "sidewalk", "path", "ground"}
PED_INFRA = {"crosswalk", "sidewalk", "path"}


# ================================================================== records
@dataclass
class Road:
    id: str
    osm_way: int
    name: str
    hclass: str
    pts: list[Pt]
    lanes: int
    width: float
    oneway: bool
    speed: float
    sidewalk_left: float          # width in m, 0 = none
    sidewalk_right: float
    start_node: str
    end_node: str
    trim_start: float = 0.0       # junction trimming (m) used by XODR + renderer
    trim_end: float = 0.0

    @property
    def length(self) -> float:
        return geo.polyline_length(self.pts)

    @property
    def kind(self) -> str:
        return "road"


@dataclass
class Junction:
    id: str
    pos: Pt
    roads: list[str]              # incident road ids
    radius: float
    signalized: bool = False
    signal_id: Optional[str] = None
    polygon: list[Pt] = field(default_factory=list)       # asphalt
    corners: list[list[Pt]] = field(default_factory=list)  # sidewalk corner patches

    kind = "junction"


@dataclass
class Crossing:
    id: str
    road: str
    s: float
    pos: Pt
    heading: float                # direction of walking across (left->right is irrelevant; dir of u axis)
    length: float                 # across the road
    width: float                  # depth along the road
    control: str                  # "zebra" | "signals" | "uncontrolled"
    signal_id: Optional[str] = None

    kind = "crossing"

    def endpoints(self) -> tuple[Pt, Pt]:
        """(start, end): start is on the road's RIGHT side, end on the LEFT side."""
        dx, dy = math.cos(self.heading), math.sin(self.heading)
        h = self.length / 2.0
        return ((self.pos[0] - dx * h, self.pos[1] - dy * h),
                (self.pos[0] + dx * h, self.pos[1] + dy * h))


@dataclass
class Signal:
    id: str
    pos: Pt
    road: Optional[str]
    kind: str                     # "vehicle" | "pedestrian"
    crossing: Optional[str] = None


@dataclass
class Prop:
    id: str
    ptype: str                    # bus_stop, waste_basket, bench, tree, street_lamp, bollard, ...
    pos: Pt
    heading: float
    road: Optional[str] = None
    name: str = ""

    kind = "prop"


@dataclass
class Building:
    id: str
    pts: list[Pt]
    height: float
    name: str = ""

    kind = "building"


@dataclass
class Barrier:
    id: str
    pts: list[Pt]
    height: float
    btype: str

    kind = "barrier"


@dataclass
class Area:
    id: str
    atype: str                    # water | green
    pts: list[Pt]

    kind = "area"


@dataclass
class Path:
    id: str
    pts: list[Pt]
    width: float
    ptype: str                    # footway | path | pedestrian | cycleway | steps

    kind = "path"


@dataclass
class Railway:
    id: str
    pts: list[Pt]
    rtype: str

    kind = "railway"


# ================================================================== model
class MapModel:
    def __init__(self, proj: geo.Projection):
        self.proj = proj
        self.roads: list[Road] = []
        self.junctions: list[Junction] = []
        self.crossings: list[Crossing] = []
        self.signals: list[Signal] = []
        self.props: list[Prop] = []
        self.buildings: list[Building] = []
        self.barriers: list[Barrier] = []
        self.areas: list[Area] = []
        self.paths: list[Path] = []
        self.railways: list[Railway] = []
        self.bounds: tuple[float, float, float, float] = (0, 0, 0, 0)  # xmin, ymin, xmax, ymax
        self._graph = None
        self._index: dict[str, Any] = {}

    # ------------------------------------------------------------ lookup
    def reindex(self) -> None:
        idx: dict[str, Any] = {}
        for coll in (self.roads, self.junctions, self.crossings, self.signals, self.props,
                     self.buildings, self.barriers, self.areas, self.paths, self.railways):
            for o in coll:
                idx[o.id] = o
        for r in self.roads:
            if r.sidewalk_left > 0:
                idx[f"sidewalk_{r.id}_left"] = ("sidewalk", r, +1)
            if r.sidewalk_right > 0:
                idx[f"sidewalk_{r.id}_right"] = ("sidewalk", r, -1)
        self._index = idx
        self._graph = None

    def get(self, fid: str) -> Any:
        if not self._index:
            self.reindex()
        return self._index.get(fid)

    def road(self, rid: str) -> Road:
        o = self.get(rid)
        if not isinstance(o, Road):
            raise KeyError(f"unknown road '{rid}'")
        return o

    # ------------------------------------------------------- parametric points
    def feature_point(self, fid: str, u: float = 0.5, v: float = 0.0) -> tuple[Pt, float]:
        """Resolve ``ObjectParametricPosition(fid, u, v)`` -> (xy, heading).

        u in [0,1] runs along the feature's main axis, v in [-1,1] across it.
        * road/path/sidewalk: u along travel direction, v across (+ = left)
        * crossing: u from the road's right side to its left side, v along the road
        * point features (signal, prop, junction, building): position (+ heading)
        """
        o = self.get(fid)
        if o is None:
            raise KeyError(f"unknown feature '{fid}'")
        u = min(1.0, max(0.0, u))
        v = min(1.0, max(-1.0, v))
        if isinstance(o, Road):
            p, h = geo.point_at(o.pts, o.length * u)
            n = (-math.sin(h), math.cos(h))
            off = v * o.width / 2.0
            return (p[0] + n[0] * off, p[1] + n[1] * off), h
        if isinstance(o, Crossing):
            a, b = o.endpoints()
            p = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
            n = (-math.sin(o.heading), math.cos(o.heading))
            off = v * o.width / 2.0
            return (p[0] + n[0] * off, p[1] + n[1] * off), o.heading
        if isinstance(o, Path):
            p, h = geo.point_at(o.pts, geo.polyline_length(o.pts) * u)
            n = (-math.sin(h), math.cos(h))
            return (p[0] + n[0] * v * o.width / 2, p[1] + n[1] * v * o.width / 2), h
        if isinstance(o, tuple) and o[0] == "sidewalk":
            _, r, side = o
            w = r.sidewalk_left if side > 0 else r.sidewalk_right
            c = geo.offset_polyline(r.pts, side * (r.width / 2 + w / 2))
            lo, hi = r.trim_start, r.length - r.trim_end
            p, h = geo.point_at(c, lo + (hi - lo) * u)
            n = (-math.sin(h), math.cos(h))
            return (p[0] + n[0] * v * w / 2, p[1] + n[1] * v * w / 2), h
        if isinstance(o, (Building, Barrier, Area, Railway)):
            c = geo.polygon_centroid(o.pts)
            return c, 0.0
        pos = getattr(o, "pos")
        return (pos[0], pos[1]), getattr(o, "heading", 0.0)

    # ----------------------------------------------------------- surfaces
    def nearest_road(self, p: Pt) -> tuple[Optional[Road], float, float, float]:
        """(road, s, t, dist) of the closest road centre-line."""
        best: tuple[Optional[Road], float, float, float] = (None, 0.0, 0.0, 1e18)
        for r in self.roads:
            s, t, _, _ = geo.project_to_polyline(r.pts, p)
            if abs(t) < best[3]:
                best = (r, s, t, abs(t))
        return best

    def surface_at(self, p: Pt) -> str:
        """Classify a ground point. Priority: crosswalk > building/water > road > sidewalk > path > ground."""
        for c in self.crossings:
            q = _local(p, c.pos, c.heading)
            if abs(q[0]) <= c.length / 2 and abs(q[1]) <= c.width / 2:
                return "crosswalk"
        for b in self.buildings:
            if _in_bbox(p, b.pts) and geo.point_in_polygon(b.pts, p):
                return "building"
        for a in self.areas:
            if a.atype == "water" and _in_bbox(p, a.pts) and geo.point_in_polygon(a.pts, p):
                return "water"
        on_sidewalk = False
        for r in self.roads:
            s, t, _, _ = geo.project_to_polyline(r.pts, p)
            half = r.width / 2
            if abs(t) <= half:
                return "road"
            w = r.sidewalk_left if t > 0 else r.sidewalk_right
            if w > 0 and abs(t) <= half + w:
                on_sidewalk = True
        for j in self.junctions:
            if geo.dist(p, j.pos) <= j.radius * 0.8:
                return "road"
        if on_sidewalk:
            return "sidewalk"
        for pa in self.paths:
            if geo.dist_to_polyline(pa.pts, p) <= pa.width / 2:
                return "path"
        return "ground"

    def is_walkable(self, p: Pt, allowed: Optional[set[str]] = None) -> bool:
        return self.surface_at(p) in (allowed or WALKABLE)

    # ------------------------------------------------------------- graph
    @property
    def ped_graph(self):
        from .pedgraph import PedGraph
        if self._graph is None:
            self._graph = PedGraph.build(self)
        return self._graph

    def kerb_slots(self, road_id: str, side: str = "right", spacing: float = 7.0,
                   margin: float = 6.0, offset: float = 1.2) -> list[dict]:
        """Candidate parked-vehicle positions along a kerb. Deterministic geometry helper."""
        r = self.road(road_id)
        sgn = +1 if side == "left" else -1
        lo, hi = r.trim_start + margin, r.length - r.trim_end - margin
        out, s, i = [], lo, 0
        while s <= hi:
            p, h = geo.point_at(r.pts, s)
            n = (-math.sin(h), math.cos(h))
            d = sgn * (r.width / 2 - offset)
            out.append({"slot": i, "s": round(s, 2),
                        "x": round(p[0] + n[0] * d, 3), "y": round(p[1] + n[1] * d, 3),
                        "heading": round(h if sgn < 0 else geo.wrap_pi(h + math.pi), 4)})
            s += spacing
            i += 1
        return out

    # --------------------------------------------------------- serialisation
    def to_dict(self) -> dict:
        def pts(l):
            return [[round(x, 3), round(y, 3)] for x, y in l]

        d: dict[str, Any] = {
            "format": "usg-scene-map/1",
            "origin": self.proj.to_dict(),
            "bounds": list(self.bounds),
            "roads": [dict(id=r.id, osm_way=r.osm_way, name=r.name, hclass=r.hclass, pts=pts(r.pts),
                           lanes=r.lanes, width=r.width, oneway=r.oneway, speed=r.speed,
                           sidewalk_left=r.sidewalk_left, sidewalk_right=r.sidewalk_right,
                           start_node=r.start_node, end_node=r.end_node,
                           trim_start=round(r.trim_start, 3), trim_end=round(r.trim_end, 3))
                      for r in self.roads],
            "junctions": [dict(id=j.id, pos=list(j.pos), roads=j.roads, radius=j.radius,
                               signalized=j.signalized, signal_id=j.signal_id,
                               polygon=pts(j.polygon), corners=[pts(c) for c in j.corners])
                          for j in self.junctions],
            "crossings": [dict(id=c.id, road=c.road, s=round(c.s, 3), pos=list(c.pos),
                               heading=c.heading, length=c.length, width=c.width,
                               control=c.control, signal_id=c.signal_id) for c in self.crossings],
            "signals": [asdict(s) for s in self.signals],
            "props": [dict(id=p.id, ptype=p.ptype, pos=list(p.pos), heading=p.heading,
                           road=p.road, name=p.name) for p in self.props],
            "buildings": [dict(id=b.id, pts=pts(b.pts), height=b.height, name=b.name)
                          for b in self.buildings],
            "barriers": [dict(id=b.id, pts=pts(b.pts), height=b.height, btype=b.btype)
                         for b in self.barriers],
            "areas": [dict(id=a.id, atype=a.atype, pts=pts(a.pts)) for a in self.areas],
            "paths": [dict(id=p.id, pts=pts(p.pts), width=p.width, ptype=p.ptype) for p in self.paths],
            "railways": [dict(id=r.id, pts=pts(r.pts), rtype=r.rtype) for r in self.railways],
        }
        g = self.ped_graph
        d["ped_graph"] = g.to_dict()
        return d

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=1)

    @staticmethod
    def from_dict(d: dict) -> "MapModel":
        m = MapModel(geo.Projection.from_dict(d["origin"]))
        m.bounds = tuple(d["bounds"])  # type: ignore[assignment]
        t = lambda l: [(float(x), float(y)) for x, y in l]  # noqa: E731
        for r in d["roads"]:
            m.roads.append(Road(id=r["id"], osm_way=r["osm_way"], name=r["name"], hclass=r["hclass"],
                                pts=t(r["pts"]), lanes=r["lanes"], width=r["width"], oneway=r["oneway"],
                                speed=r["speed"], sidewalk_left=r["sidewalk_left"],
                                sidewalk_right=r["sidewalk_right"], start_node=r["start_node"],
                                end_node=r["end_node"], trim_start=r["trim_start"], trim_end=r["trim_end"]))
        for j in d["junctions"]:
            m.junctions.append(Junction(id=j["id"], pos=tuple(j["pos"]), roads=j["roads"], radius=j["radius"],
                                        signalized=j["signalized"], signal_id=j["signal_id"],
                                        polygon=t(j["polygon"]), corners=[t(c) for c in j["corners"]]))
        for c in d["crossings"]:
            m.crossings.append(Crossing(id=c["id"], road=c["road"], s=c["s"], pos=tuple(c["pos"]),
                                        heading=c["heading"], length=c["length"], width=c["width"],
                                        control=c["control"], signal_id=c["signal_id"]))
        for s in d["signals"]:
            m.signals.append(Signal(id=s["id"], pos=tuple(s["pos"]), road=s["road"], kind=s["kind"],
                                    crossing=s.get("crossing")))
        for p in d["props"]:
            m.props.append(Prop(id=p["id"], ptype=p["ptype"], pos=tuple(p["pos"]), heading=p["heading"],
                                road=p["road"], name=p["name"]))
        for b in d["buildings"]:
            m.buildings.append(Building(id=b["id"], pts=t(b["pts"]), height=b["height"], name=b["name"]))
        for b in d["barriers"]:
            m.barriers.append(Barrier(id=b["id"], pts=t(b["pts"]), height=b["height"], btype=b["btype"]))
        for a in d["areas"]:
            m.areas.append(Area(id=a["id"], atype=a["atype"], pts=t(a["pts"])))
        for p in d["paths"]:
            m.paths.append(Path(id=p["id"], pts=t(p["pts"]), width=p["width"], ptype=p["ptype"]))
        for r in d["railways"]:
            m.railways.append(Railway(id=r["id"], pts=t(r["pts"]), rtype=r["rtype"]))
        m.reindex()
        return m

    @staticmethod
    def load(path) -> "MapModel":
        with open(path, "r", encoding="utf-8") as f:
            return MapModel.from_dict(json.load(f))


# ================================================================== helpers
def _local(p: Pt, origin: Pt, hdg: float) -> Pt:
    """Express p in a frame at origin rotated by hdg: (along-heading, left-of-heading)."""
    dx, dy = p[0] - origin[0], p[1] - origin[1]
    c, s = math.cos(hdg), math.sin(hdg)
    return (dx * c + dy * s, -dx * s + dy * c)


def _in_bbox(p: Pt, pts: list[Pt]) -> bool:
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    return min(xs) <= p[0] <= max(xs) and min(ys) <= p[1] <= max(ys)
