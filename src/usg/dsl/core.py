"""Core DSL value types: Place, MapQuery (read-only map facade) and the VRTask ontology.

The VRTask ontology is carried inside standard OpenSCENARIO as
``UserDefinedAction > CustomCommandAction type="VR_TASK"`` with *real* child
elements (not escaped text), so the file stays well-formed OpenSCENARIO and any
tool that ignores custom commands (esmini, CARLA ScenarioRunner, ...) still loads it.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional, Sequence

from scenariogeneration import xosc

from .. import geo
from ..mapmodel import Crossing, MapModel, Road
from ..spec import formula as F

# ============================================================== places
@dataclass(frozen=True)
class Place:
    """A point in the shared metric frame, optionally remembering which map feature it came from."""
    x: float
    y: float
    z: float = 0.0
    h: float = 0.0
    feature: Optional[str] = None
    u: Optional[float] = None
    v: Optional[float] = None
    label: str = ""

    def xy(self) -> tuple[float, float]:
        return (self.x, self.y)

    def dist(self, other: "Place") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def shifted(self, ahead: float = 0.0, left: float = 0.0) -> "Place":
        c, s = math.cos(self.h), math.sin(self.h)
        return Place(self.x + c * ahead - s * left, self.y + s * ahead + c * left, self.z, self.h,
                     None, None, None, self.label)

    def facing(self, other: "Place") -> "Place":
        return Place(self.x, self.y, self.z, math.atan2(other.y - self.y, other.x - self.x),
                     self.feature, self.u, self.v, self.label)


def at(x: float, y: float, heading: float = 0.0) -> Place:
    """A raw world position (metres, ENU frame of the map)."""
    return Place(float(x), float(y), 0.0, float(heading))


# ============================================================== map facade
class MapQuery:
    """Read-only, plain-data view of the map for scenario scripts and the agent's tools."""

    def __init__(self, model: MapModel):
        self._m = model

    # ---- listings (plain dicts) ------------------------------------------------
    def overview(self) -> dict:
        m = self._m
        x0, y0, x1, y1 = m.bounds
        return {"extent_m": [round(x1 - x0), round(y1 - y0)], "bounds": [round(v, 1) for v in m.bounds],
                "frame": "x=east, y=north, metres, heading in radians (0=east, CCW)",
                "counts": {"roads": len(m.roads), "junctions": len(m.junctions),
                           "crossings": len(m.crossings), "signals": len(m.signals),
                           "bus_stops": sum(p.ptype == "bus_stop" for p in m.props),
                           "props": len(m.props), "buildings": len(m.buildings),
                           "paths": len(m.paths), "water": sum(a.atype == "water" for a in m.areas),
                           "railways": len(m.railways)}}

    def roads(self) -> list[dict]:
        return [{"id": r.id, "name": r.name, "class": r.hclass, "length": round(r.length, 1),
                 "lanes": r.lanes, "width": round(r.width, 2), "oneway": r.oneway,
                 "speed_limit_mps": round(r.speed, 1),
                 "sidewalk": {"left": r.sidewalk_left, "right": r.sidewalk_right},
                 "start": [round(r.pts[0][0], 1), round(r.pts[0][1], 1)],
                 "end": [round(r.pts[-1][0], 1), round(r.pts[-1][1], 1)],
                 "trim": [round(r.trim_start, 1), round(r.trim_end, 1)]} for r in self._m.roads]

    def crossings(self, control: Optional[str] = None) -> list[dict]:
        out = []
        for c in self._m.crossings:
            if control and c.control != control:
                continue
            a, b = c.endpoints()
            out.append({"id": c.id, "road": c.road, "road_name": self._m.road(c.road).name,
                        "control": c.control, "signal_id": c.signal_id,
                        "center": [round(c.pos[0], 1), round(c.pos[1], 1)],
                        "road_s": round(c.s, 1), "length_m": round(c.length, 1),
                        "start_side": [round(a[0], 1), round(a[1], 1)],
                        "end_side": [round(b[0], 1), round(b[1], 1)],
                        "walking_dir_start_to_end_rad": round(c.heading, 3)})
        return out

    def road(self, road_id: str) -> dict:
        r = self._m.road(road_id)
        return {"id": r.id, "name": r.name, "class": r.hclass, "length": round(r.length, 1), "width": round(r.width, 2),
                "lanes": r.lanes, "oneway": r.oneway, "speed_limit_mps": round(r.speed, 1),
                "sidewalk_left": r.sidewalk_left, "sidewalk_right": r.sidewalk_right,
                "trim": [round(r.trim_start, 1), round(r.trim_end, 1)]}

    def junctions(self) -> list[dict]:
        return [{"id": j.id, "pos": [round(j.pos[0], 1), round(j.pos[1], 1)], "roads": j.roads,
                 "signalized": j.signalized, "arms": len(j.roads)} for j in self._m.junctions]

    def signals(self) -> list[dict]:
        return [{"id": s.id, "kind": s.kind, "pos": [round(s.pos[0], 1), round(s.pos[1], 1)],
                 "road": s.road, "crossing": s.crossing} for s in self._m.signals]

    def props(self, ptype: Optional[str] = None) -> list[dict]:
        return [{"id": p.id, "type": p.ptype, "pos": [round(p.pos[0], 1), round(p.pos[1], 1)],
                 "road": p.road, "name": p.name} for p in self._m.props if not ptype or p.ptype == ptype]

    def bus_stops(self) -> list[dict]:
        return self.props("bus_stop")

    def paths(self) -> list[dict]:
        return [{"id": p.id, "type": p.ptype, "width": p.width,
                 "length": round(geo.polyline_length(p.pts), 1),
                 "start": [round(p.pts[0][0], 1), round(p.pts[0][1], 1)],
                 "end": [round(p.pts[-1][0], 1), round(p.pts[-1][1], 1)]} for p in self._m.paths]

    def buildings(self, near: Optional[tuple[float, float]] = None, radius: float = 60.0) -> list[dict]:
        out = []
        for b in self._m.buildings:
            c = geo.polygon_centroid(b.pts)
            if near is None or geo.dist(c, near) <= radius:
                out.append({"id": b.id, "center": [round(c[0], 1), round(c[1], 1)], "height": b.height})
        return out

    def feature(self, fid: str) -> dict:
        o = self._m.get(fid)
        if o is None:
            raise KeyError(f"unknown feature '{fid}'")
        (x, y), h = self._m.feature_point(fid)
        return {"id": fid, "kind": o.kind if hasattr(o, "kind") else "sidewalk",
                "pos": [round(x, 2), round(y, 2)], "heading": round(h, 3)}

    # ---- geometry helpers returning Place --------------------------------------
    def place(self, fid: str, u: float = 0.5, v: float = 0.0) -> Place:
        (x, y), h = self._m.feature_point(fid, u, v)
        return Place(x, y, 0.0, h, fid, u, v, fid)

    def crossing_side(self, crossing_id: str, side: str = "start", inset: float = 1.5) -> Place:
        """Spot on the sidewalk just beyond one end of a crossing, facing across the road.

        side="start": the road's right-hand kerb, facing across; side="end": the left-hand kerb.
        """
        c = self._m.get(crossing_id)
        if not isinstance(c, Crossing):
            raise KeyError(f"'{crossing_id}' is not a crossing")
        a, b = c.endpoints()
        if side == "start":
            p, h = a, c.heading
            q = (p[0] - math.cos(c.heading) * inset, p[1] - math.sin(c.heading) * inset)
        else:
            p, h = b, geo.wrap_pi(c.heading + math.pi)
            q = (p[0] + math.cos(c.heading) * inset, p[1] + math.sin(c.heading) * inset)
        return Place(q[0], q[1], 0.0, h, crossing_id, 0.0 if side == "start" else 1.0, 0.0,
                     f"{crossing_id}:{side}")

    def along_road(self, road_id: str, s: float, t: float = 0.0) -> Place:
        r = self._m.road(road_id)
        p, h = geo.point_at(r.pts, s)
        n = (-math.sin(h), math.cos(h))
        return Place(p[0] + n[0] * t, p[1] + n[1] * t, 0.0, h, road_id, s / max(r.length, 1e-6),
                     t / max(r.width / 2, 1e-6), road_id)

    def lane_center(self, road_id: str, s: float, direction: str = "forward") -> Place:
        """Centre of the driving lane nearest the centre-line, for travel along ("forward") or against ("backward") the road's direction."""
        r = self._m.road(road_id)
        if r.oneway:                                   # all lanes run forward
            n = max(1, r.lanes)
            t = 0.0 if n == 1 else -(r.width / n) / 2  # a single lane IS the road: its centre is the centre-line
            return self.along_road(road_id, s, t)
        per = max(1, r.lanes // 2)                     # lanes per direction
        lane_w = r.width / (2 * per)
        if direction == "forward":
            return self.along_road(road_id, s, -lane_w / 2)
        pl = self.along_road(road_id, s, +lane_w / 2)
        return Place(pl.x, pl.y, 0.0, geo.wrap_pi(pl.h + math.pi), pl.feature, pl.u, pl.v, pl.label)

    def drive_route(self, road_id: str, s_from: float, s_to: float, direction: str = "forward",
                    step: float = 10.0) -> list[Place]:
        """Lane-centre waypoints for a vehicle going from s_from to s_to along one road (stays in its lane)."""
        r = self._m.road(road_id)
        a = max(0.0, min(r.length, s_from))
        b = max(0.0, min(r.length, s_to))
        n = max(1, int(abs(b - a) // step))
        return [self.lane_center(road_id, a + (b - a) * i / n, direction) for i in range(n + 1)]

    def side_of_road(self, p: Place) -> str:
        """'left' or 'right' of the nearest road's digitised direction."""
        rd, s, t, d = self._m.nearest_road(p.xy())
        return "left" if t >= 0 else "right"

    def nearest_road_id(self, p: Place) -> Optional[str]:
        rd, s, t, d = self._m.nearest_road(p.xy())
        return rd.id if rd else None

    def kerb_slots(self, road_id: str, side: str = "right", spacing: float = 7.0) -> list[Place]:
        return [Place(d["x"], d["y"], 0.0, d["heading"], road_id, None, None, f"{road_id}:{side}:{d['slot']}")
                for d in self._m.kerb_slots(road_id, side, spacing)]

    def sidewalk_at(self, road_id: str, side: str, s: float) -> Place:
        """Centre of the sidewalk strip beside a road at arc length ``s`` (side: 'left'|'right')."""
        r = self._m.road(road_id)
        w = r.sidewalk_left if side == "left" else r.sidewalk_right
        w = w if w > 0 else 1.5
        sgn = 1.0 if side == "left" else -1.0
        return self.along_road(road_id, s, sgn * (r.width / 2 + w / 2))

    def sidewalk(self, road_id: str, side: str = "right", u: float = 0.5) -> Place:
        return self.place(f"sidewalk_{road_id}_{side}", u, 0.0)

    def route(self, a: Place, b: Place, avoid_crossings: Sequence[str] = ()) -> Optional[list[Place]]:
        r = self._m.ped_graph.route(a.xy(), b.xy(), set(avoid_crossings))
        if r is None:
            return None
        pts = r["waypoints"]
        out = []
        for i, p in enumerate(pts):
            h = geo.heading(p, pts[min(i + 1, len(pts) - 1)]) if i < len(pts) - 1 else (out[-1].h if out else 0.0)
            out.append(Place(p[0], p[1], 0.0, h))
        return out

    def route_info(self, a: Place, b: Place) -> Optional[dict]:
        r = self._m.ped_graph.route(a.xy(), b.xy())
        return None if r is None else {"length_m": round(r["length"], 1), "crossings": r["crossings"],
                                         "waypoints": [[round(p[0], 1), round(p[1], 1)] for p in r["waypoints"]]}

    def surface(self, p: Place) -> str:
        return self._m.surface_at(p.xy())

    def walk_time(self, a: Place, b: Place, margin: float = 1.6) -> float:
        """A safe timeout in seconds for walking from a to b (pedestrian route at 1.2 m/s, with margin), rounded up to 5 s."""
        info = self._m.ped_graph.route(a.xy(), b.xy())
        length = info["length"] if info else a.dist(b) * 1.4
        return float(max(30, 5 * math.ceil((length / 1.2 * margin + 8) / 5)))

    def road_s_of(self, p: Place) -> float:
        """Arc length along the nearest road at which this place lies."""
        rd, s, t, d = self._m.nearest_road(p.xy())
        return float(s)

    def distance(self, a: Place, b: Place) -> float:
        return a.dist(b)


# ============================================================== task ontology
CATEGORIES = ("ptp_env", "ptp_road", "constrained_path", "env_constrained", "dynamic")
TASK_KINDS = ("go", "cross")


@dataclass
class Target:
    """Where/what the task targets. Exactly one of place / entity / entity_offset / layer."""
    place: Optional[Place] = None
    entity: Optional[str] = None                       # TaskTargetEntity
    entity_offset: Optional[tuple[str, float, float, float, float]] = None   # entity, dx, dy, dz, size
    layer: Optional[tuple[str, str]] = None            # GUST layer target (layer, name)
    name: str = "target"
    cls: str = "Location"                              # KeyItem

    def to_element(self) -> ET.Element:
        t = ET.Element("Target")
        if self.layer:
            ud = ET.SubElement(ET.SubElement(t, "UserData"), "GUST")
            ET.SubElement(ud, "LayerTarget", layer=self.layer[0], name=self.layer[1])
        elif self.entity_offset:
            e, dx, dy, dz, size = self.entity_offset
            ET.SubElement(ET.SubElement(t, "Position"), "TaskTargetEntityPosition", entity=e,
                          dx=f"{dx:g}", dy=f"{dy:g}", dz=f"{dz:g}", size=f"{size:g}")
        elif self.entity:
            ET.SubElement(t, "TaskTargetEntity", entity=self.entity)
        elif self.place:
            p = self.place
            pos = ET.SubElement(t, "Position")
            ET.SubElement(pos, "WorldPosition", x=f"{p.x:.3f}", y=f"{p.y:.3f}", z=f"{p.z:.3f}",
                          h=f"{p.h:.4f}", p="0", r="0")
            if p.feature:
                ET.SubElement(ET.SubElement(t, "UserData"), "Feature", id=p.feature,
                              u="" if p.u is None else f"{p.u:g}", v="" if p.v is None else f"{p.v:g}")
        return t


# ---- failure conditions -----------------------------------------------------------
@dataclass
class FailureCondition:
    def to_element(self) -> ET.Element:           # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class Timeout(FailureCondition):
    initial: float = 60.0
    baseline: float = 90.0

    def to_elements(self) -> list[ET.Element]:
        return [ET.Element("InitialTimeoutFailureCondition", timeout=f"{self.initial:g}"),
                ET.Element("BaselineTimeoutFailureCondition", timeout=f"{self.baseline:g}")]


@dataclass
class SurfaceAdherence(FailureCondition):
    """Fails when the user's feet leave the allowed surface class ('walkable', 'pedestrian_infra', 'crosswalk', 'road')."""
    surface: str = "pedestrian_infra"

    def to_element(self) -> ET.Element:
        return ET.Element("SurfaceAdherenceFailureCondition", surface=self.surface)


@dataclass
class FollowTrajectory(FailureCondition):
    """Fails when the user strays more than ``tolerance`` metres from the polyline."""
    vertices: list[Place] = field(default_factory=list)
    tolerance: float = 2.0
    name: str = "trajectory"

    def to_element(self) -> ET.Element:
        e = ET.Element("FollowTrajectoryFailureCondition", tolerance=f"{self.tolerance:g}")
        tr = ET.SubElement(e, "Trajectory", name=self.name, closed="false")
        poly = ET.SubElement(ET.SubElement(tr, "Shape"), "Polyline")
        for i, p in enumerate(self.vertices):
            v = ET.SubElement(poly, "Vertex", time=f"{i:g}")
            ET.SubElement(ET.SubElement(v, "Position"), "WorldPosition", x=f"{p.x:.3f}", y=f"{p.y:.3f}",
                          z=f"{p.z:.3f}")
        return e


@dataclass
class Collision(FailureCondition):
    entities: list[str] = field(default_factory=list)

    def to_element(self) -> ET.Element:
        e = ET.Element("CollisionFailureCondition")
        for n in self.entities:
            ET.SubElement(e, "EntityRef", entityRef=n)
        return e


@dataclass
class SignalViolation(FailureCondition):
    """Fails when the user steps onto the road/crossing while the crossing's pedestrian signal is not green."""
    crossing: str = ""
    signal: Optional[str] = None

    def to_element(self) -> ET.Element:
        e = ET.Element("SignalViolationFailureCondition", crossing=self.crossing)
        if self.signal:
            e.set("signal", self.signal)
        return e


@dataclass
class TriggerFailure(FailureCondition):
    """Fails when any of the named storyboard events starts (e.g. 'a car honks')."""
    events: list[str] = field(default_factory=list)

    def to_element(self) -> ET.Element:
        e = ET.Element("TriggerFailureCondition")
        for n in self.events:
            ET.SubElement(e, "Event", name=n)
        return e


# ---- the task itself --------------------------------------------------------------
@dataclass
class VRTask:
    id: int
    name: str
    kind: str                                         # go | cross
    category: str                                     # see CATEGORIES
    target: Target
    instruction: dict[str, str]
    success_feedback: dict[str, str] = field(default_factory=dict)
    failure_feedback: dict[str, str] = field(default_factory=dict)
    tolerance: float = 1.5
    max_speed: float = 3.0
    precedence: int = 1
    evaluation: str = "proximity"
    timeout: Timeout = field(default_factory=Timeout)
    failures: list[FailureCondition] = field(default_factory=list)
    depends_on: list[int] = field(default_factory=list)
    group: Optional[str] = None
    mode: str = "independent"                         # sequential | parallel | independent
    start_time: float = 0.0
    required: bool = True
    # ---- the formal task specification (see usg.spec). Explicit specs come from ScenarioBuilder.apply_spec; tasks made
    # with go_to/cross/follow_path are compiled to the SAME language by the builder, so every task ships formulas.
    spec_goal: Optional[dict] = None                  # resolved core formula (success)
    spec_safety: list = field(default_factory=list)   # resolved core formulas (any violated -> the task fails)
    explicit_spec: bool = False                       # True when the model wrote the formulas itself
    spec_raw: Optional[dict] = None                   # the readable macro form {'goal': call, 'safety': [call,...]} (round-trips through apply_spec)

    def to_element(self) -> ET.Element:
        e = ET.Element("VRTask", id=str(self.id), name=self.name, category=self.category)
        if self.group:
            e.set("group", self.group)
            e.set("mode", self.mode)
        e.set("required", "true" if self.required else "false")
        ET.SubElement(e, "EventName").text = f"task_{self.id}_{self.name}"
        g = ET.SubElement(e, "Goal")
        ET.SubElement(g, "Type").text = self.kind
        ET.SubElement(g, "Target").text = self.target.name
        ET.SubElement(g, "KeyItem").text = self.target.cls
        ins = ET.SubElement(e, "Instructions")
        for lang, txt in sorted(self.instruction.items()):
            ET.SubElement(ins, "Text", lang=lang).text = txt
        fb = ET.SubElement(e, "Feedback")
        for lang, txt in sorted(self.success_feedback.items()):
            ET.SubElement(fb, "Success", lang=lang).text = txt
        for lang, txt in sorted(self.failure_feedback.items()):
            ET.SubElement(fb, "Failure", lang=lang).text = txt
        for d in self.depends_on:
            ET.SubElement(e, "DependsOn", task=str(d))
        e.append(self.target.to_element())
        c = ET.SubElement(e, "Constraints")
        ET.SubElement(c, "precedence").text = str(self.precedence)
        ET.SubElement(c, "evaluation").text = self.evaluation
        ET.SubElement(c, "MaxSpeed", value=f"{self.max_speed:g}")
        ET.SubElement(c, "Tolerance", value=f"{self.tolerance:g}")
        ET.SubElement(c, "StartTime", value=f"{self.start_time:g}")
        f = ET.SubElement(e, "FailureCondition")
        for el in self.timeout.to_elements():
            f.append(el)
        for fc in self.failures:
            f.append(fc.to_element())
        if self.spec_goal is not None:
            sp = ET.SubElement(e, "Spec", origin="spec" if self.explicit_spec else "helper")
            ET.SubElement(sp, "Goal").append(F.to_xml(self.spec_goal))
            sf = ET.SubElement(sp, "Safety")
            for fm in self.spec_safety:
                sf.append(F.to_xml(fm))
        return e


class VRTaskCommand(xosc.CustomCommandAction):
    """CustomCommandAction(type='VR_TASK') whose payload is a real <VRTask> element."""

    def __init__(self, task: VRTask):
        super().__init__("VR_TASK", "")
        self.task = task

    def get_element(self) -> ET.Element:
        el = ET.Element("CustomCommandAction", attrib={"type": "VR_TASK"})
        el.append(self.task.to_element())
        return el


def task_action(task: VRTask) -> xosc.UserDefinedAction:
    """Wrap a task in the spec-compliant ``UserDefinedAction`` element."""
    return xosc.UserDefinedAction(VRTaskCommand(task))
