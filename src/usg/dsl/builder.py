"""ScenarioBuilder: deterministic Storyboard assembly (replaces LLM "stage 3" and "stage 4").

The LLM only decides *content* (entities, routes, tasks, text); this class turns that
into a valid OpenSCENARIO storyboard via ``scenariogeneration`` and guarantees the
Event -> Maneuver -> ManeuverGroup -> Act -> Story -> Storyboard structure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Union

from scenariogeneration import xosc

from .. import geo
from ..signals import lamp_state, signal_kind, signal_numbers
from ..spec import formula as F
from ..spec.axes import category_of, task_axes
from .core import (CATEGORIES, Collision, FailureCondition, FollowTrajectory, MapQuery, Place,
                   SignalViolation, SurfaceAdherence, Target, Timeout, TriggerFailure, VRTask,
                   task_action)

USER = "User"
SPEC_LEVEL = 2          # 1 = library definitions only, 2 = the model may define its own (set by the sandbox)
VEHICLE_MODELS = ("car_white", "car_red", "car_blue", "car_yellow", "van_red", "bus_blue", "truck_yellow")
WALKER_MODELS = ("ped_a", "ped_b", "ped_c")
Text = Union[str, dict]


# ---------------------------------------------------------------- start conditions
@dataclass(frozen=True)
class StartWhen:
    kind: str                       # time | task_started | task_done | user_within
    value: float = 0.0
    task: Optional[int] = None


def when_time(t: float = 0.0) -> StartWhen:
    return StartWhen("time", float(t))


def when_task_starts(task: "TaskHandle") -> StartWhen:
    return StartWhen("task_started", 0.0, task.id)


def when_task_done(task: "TaskHandle") -> StartWhen:
    return StartWhen("task_done", 0.0, task.id)


def when_user_within(metres: float) -> StartWhen:
    return StartWhen("user_within", float(metres))


@dataclass
class TaskHandle:
    id: int
    name: str

    @property
    def event(self) -> str:
        return f"task_{self.id}_{self.name}"


@dataclass
class _Entity:
    name: str
    role: str                       # user | vehicle | walker
    model: str
    start: Place
    speed: float = 0.0
    route: list[Place] = field(default_factory=list)
    start_when: StartWhen = field(default_factory=lambda: StartWhen("time", 0.0))
    moving: bool = False


@dataclass
class _SignalCycle:
    signal: str
    green: float
    red: float
    offset: float
    initial: str


_REASONS = {
    "collision_free": "collision with {entity}", "keep_clear": "too close to {entity}", "stay_on": "left {surface}",
    "stay_near_path": "left the marked path", "obey_signal": "crossed on red", "no_event": "event {name} occurred",
    "pace": "wrong walking pace", "follow": "lost the person to follow",
}


def _reason(raw: dict, core: dict) -> str:
    """What the participant is told when this safety rule is the one that failed."""
    if isinstance(raw, dict) and raw.get("op") == "call" and raw.get("name") in _REASONS:
        args = raw.get("args", {})
        try:
            return _REASONS[raw["name"]].format(**{k: v for k, v in args.items() if isinstance(v, (str, int, float))})
        except KeyError:
            pass
    return "rule broken: " + F.describe(core)[:70]


def _txt(t: Optional[Text], default: str) -> dict:
    if t is None:
        return {"en": default}
    return dict(t) if isinstance(t, dict) else {"en": str(t)}


class ScenarioBuilder:
    def __init__(self, name: str, map: MapQuery, scenario_type: Optional[str] = None,
                 description: str = "", author: str = "usg"):
        self.name = name
        self.map = map
        self.scenario_type = scenario_type
        self.description = description
        self.author = author
        self.entities: list[_Entity] = []
        self.tasks: list[VRTask] = []
        self._task_start: dict[int, StartWhen] = {}
        self.cycles: list[_SignalCycle] = []
        self.virtual_signals: dict[str, Place] = {}
        self._extra_events: list[tuple[str, xosc.Event]] = []
        self.hud_intro: dict = {}

    # ================================================================ entities
    def user(self, start: Optional[Place] = None, name: str = USER) -> str:
        if start is None:                      # no start given: the participant is placed automatically before the first goal zone
            return name
        if any(e.role == "user" for e in self.entities):
            raise ValueError("the scenario already has a user")
        self.entities.append(_Entity(name, "user", "user_rig", start))
        return name

    def vehicle(self, name: str, start: Place, route: Sequence[Place] = (), speed: float = 8.0,
                model: str = "car_white", start_when: Optional[StartWhen] = None) -> str:
        """A vehicle. With a ``route`` it drives it at ``speed`` m/s; without, it stays parked."""
        self._check_name(name)
        if model not in VEHICLE_MODELS:
            raise ValueError(f"unknown vehicle model '{model}', choose from {VEHICLE_MODELS}")
        route = list(route)
        self.entities.append(_Entity(name, "vehicle", model, start, speed if route else 0.0, route,
                                     start_when or when_time(0.0), moving=bool(route)))
        return name

    def parked_vehicle(self, name: str, slot: Place, model: str = "car_white") -> str:
        return self.vehicle(name, slot, (), 0.0, model)

    def walker(self, name: str, start: Place, route: Sequence[Place] = (), speed: float = 1.3,
               model: str = "ped_a", start_when: Optional[StartWhen] = None) -> str:
        """A non-player pedestrian (NPC)."""
        self._check_name(name)
        route = list(route)
        self.entities.append(_Entity(name, "walker", model, start, speed if route else 0.0, route,
                                     start_when or when_time(0.0), moving=bool(route)))
        return name

    def _check_name(self, name: str) -> None:
        if any(e.name == name for e in self.entities):
            raise ValueError(f"duplicate entity name '{name}'")
        if name == USER:
            raise ValueError("'User' is reserved for the player")

    def _moving(self) -> set[str]:
        return {e.name for e in self.entities if e.moving}

    # ================================================================ signals
    def signal_cycle(self, ref: str, green: float = 15.0, red: float = 20.0, offset: float = 0.0,
                     initial: str = "red") -> str:
        """Pedestrian signal cycle for a crossing id (or signal id). Returns the signal name."""
        sig = ref
        m = self.map._m
        o = m.get(ref)
        if o is None or getattr(o, "kind", None) not in ("crossing", "signal"):
            raise ValueError(f"signal_cycle: '{ref}' is neither a crossing id nor a signal id of this map. Use a crossing id such as "
                             f"{[c.id for c in m.crossings][:3]} or a signal id such as {[x.id for x in m.signals][:3]} (see MAP.crossings(), MAP.signals())")
        if o is not None and o.kind == "crossing":
            sig = o.signal_id or f"{o.id}_ped"
            if not o.signal_id:
                self.virtual_signals[sig] = Place(o.pos[0], o.pos[1], 0.0, o.heading, o.id)
        if initial not in ("red", "green"):
            raise ValueError("initial must be 'red' or 'green'")
        self.cycles.append(_SignalCycle(sig, float(green), float(red), float(offset), initial))
        return sig

    # ================================================================ tasks
    def _new_task(self, kind: str, name: str, target: Target, instruction: Optional[Text],
                  success: Optional[Text], failure: Optional[Text], tolerance: float, max_speed: float,
                  timeout: float, baseline: Optional[float], failures: Sequence[FailureCondition],
                  after: Sequence["TaskHandle"], start_time: float, evaluation: str,
                  avoid: Sequence[str], required: bool) -> TaskHandle:
        tid = len(self.tasks) + 1
        fl = list(failures)
        if avoid:
            fl.append(Collision(list(avoid)))
        cat = ""   # derived lazily in _finalize() once all entities exist
        task = VRTask(id=tid, name=name, kind=kind, category=cat, target=target,
                      instruction=_txt(instruction, f"Task {tid}"),
                      success_feedback=_txt(success, "Well done!"),
                      failure_feedback=_txt(failure, "That did not work. Try again."),
                      tolerance=tolerance, max_speed=max_speed, evaluation=evaluation,
                      timeout=Timeout(float(timeout), float(baseline if baseline else timeout * 1.5)),
                      failures=fl, depends_on=[a.id for a in after], start_time=start_time,
                      required=required)
        self.tasks.append(task)
        return TaskHandle(tid, name)

    def go_to(self, target: Place, instruction: Optional[Text] = None, name: Optional[str] = None,
              tolerance: float = 1.5, max_speed: float = 3.0, timeout: float = 60.0,
              baseline_timeout: Optional[float] = None, avoid: Sequence[str] = (),
              on_surface: Optional[str] = None, after: Sequence[TaskHandle] = (),
              start_time: float = 0.0, success: Optional[Text] = None, failure: Optional[Text] = None,
              target_name: str = "destination", required: bool = True) -> TaskHandle:
        """Walk to a location. ``on_surface`` adds a SurfaceAdherence failure ('walkable','pedestrian_infra','crosswalk','road')."""
        fl: list[FailureCondition] = [SurfaceAdherence(on_surface)] if on_surface else []
        return self._new_task("go", name or f"go_{len(self.tasks) + 1}",
                              Target(place=target, name=target_name, cls="Location"), instruction, success,
                              failure, tolerance, max_speed, timeout, baseline_timeout, fl, after,
                              start_time, "proximity", avoid, required)

    def cross(self, crossing_id: str, from_side: str = "start", instruction: Optional[Text] = None,
              name: Optional[str] = None, tolerance: float = 1.5, max_speed: float = 3.0,
              timeout: float = 60.0, baseline_timeout: Optional[float] = None,
              avoid: Sequence[str] = (), obey_signal: bool = True, stay_on_crossing: bool = False,
              after: Sequence[TaskHandle] = (), start_time: float = 0.0,
              success: Optional[Text] = None, failure: Optional[Text] = None,
              required: bool = True) -> TaskHandle:
        """Cross the road at a crossing, starting from its ``from_side`` ('start' or 'end') kerb."""
        far = "end" if from_side == "start" else "start"
        target = self.map.crossing_side(crossing_id, far, inset=1.0)
        fl: list[FailureCondition] = []
        c = self.map._m.get(crossing_id)
        if obey_signal and c is not None and c.control == "signals":
            sig = self.signal_name_for(crossing_id)
            fl.append(SignalViolation(crossing_id, sig))
        if stay_on_crossing:
            fl.append(SurfaceAdherence("crosswalk"))
        return self._new_task("cross", name or f"cross_{crossing_id}",
                              Target(place=target, name=crossing_id, cls="Crosswalk"), instruction, success,
                              failure, tolerance, max_speed, timeout, baseline_timeout, fl, after,
                              start_time, "proximity", avoid, required)

    def follow_path(self, waypoints: Sequence[Place], instruction: Optional[Text] = None,
                    name: Optional[str] = None, tolerance: float = 2.0, corridor: Optional[float] = None,
                    max_speed: float = 3.0, timeout: float = 90.0, baseline_timeout: Optional[float] = None,
                    avoid: Sequence[str] = (), after: Sequence[TaskHandle] = (), start_time: float = 0.0,
                    success: Optional[Text] = None, failure: Optional[Text] = None,
                    required: bool = True) -> TaskHandle:
        """Reach the last waypoint while staying within ``corridor`` metres of the polyline (constrained path)."""
        wps = list(waypoints)
        if len(wps) < 2:
            raise ValueError("follow_path needs at least 2 waypoints")
        fl: list[FailureCondition] = [FollowTrajectory(wps, corridor or tolerance, f"path_{len(self.tasks) + 1}")]
        return self._new_task("go", name or f"follow_path_{len(self.tasks) + 1}",
                              Target(place=wps[-1], name="path_end", cls="Location"), instruction, success,
                              failure, tolerance, max_speed, timeout, baseline_timeout, fl, after,
                              start_time, "trajectory_following", avoid, required)

    def sequence(self, tasks: Sequence[TaskHandle], group: str = "sequence") -> None:
        """Make the tasks dependent: each starts only when the previous one finished."""
        byid = {t.id: t for t in self.tasks}
        for prev, nxt in zip(tasks[:-1], tasks[1:]):
            t = byid[nxt.id]
            if prev.id not in t.depends_on:
                t.depends_on.append(prev.id)
        for h in tasks:
            byid[h.id].group, byid[h.id].mode = group, "sequential"

    def parallel(self, tasks: Sequence[TaskHandle], group: str = "parallel") -> None:
        """Independent tasks that all start together and may be completed in any order."""
        byid = {t.id: t for t in self.tasks}
        for h in tasks:
            byid[h.id].group, byid[h.id].mode = group, "parallel"

    def _lamps(self, signal: str, state: str) -> str:
        """The state string standard consumers expect for this signal's type (see usg.signals)."""
        return lamp_state(signal_kind(self.map._m, signal), state)

    def signal_name_for(self, crossing_id: str) -> str:
        for cy in self.cycles:
            c = self.map._m.get(crossing_id)
            if c is not None and cy.signal in (c.signal_id, f"{c.id}_ped"):
                return cy.signal
        c = self.map._m.get(crossing_id)
        return (c.signal_id if c and c.signal_id else f"{crossing_id}_ped")

    # ================================================================ escape hatch
    def add_event(self, actor: str, event: xosc.Event) -> None:
        """Add any raw scenariogeneration Event for an entity (full OpenSCENARIO power)."""
        self._extra_events.append((actor, event))

    # ================================================================ timing
    def horizon(self) -> float:
        end: dict[int, float] = {}
        for t in sorted(self.tasks, key=lambda t: t.id):
            st = max([t.start_time] + [end.get(d, 0.0) for d in t.depends_on])
            end[t.id] = st + t.timeout.baseline
        return (max(end.values()) if end else 30.0) + 5.0

    AUTO_USER_DISTANCE = 18.0       # metres of walking between the automatic start and the first goal zone

    def _ensure_user(self) -> None:
        """A script that applies a specification may omit ``scenario.user(...)``: the participant is then placed on the
        walkable network about 18 m (route distance) before the first goal zone, facing it."""
        if any(e.role == "user" for e in self.entities) or not any(t.explicit_spec for t in self.tasks):
            return
        goal = next((z for t in self.tasks if t.explicit_spec for z in F.zones_in(t.spec_goal) if z["kind"] in ("disc", "rect")), None)
        if goal is None:
            return
        g = (goal["x"], goal["y"]) if goal["kind"] == "disc" else (goal["cx"], goal["cy"])
        pg = self.map._m.ped_graph
        src = pg.nearest(g)
        import heapq
        dist = {src: 0.0}
        heap = [(0.0, src)]
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist.get(n, 1e18) or d > 120:
                continue
            for m_, w, _kind, _ref in pg.adj[n]:
                nd = d + w
                if nd < dist.get(m_, 1e18):
                    dist[m_] = nd
                    heapq.heappush(heap, (nd, m_))
        vehicles = [e.start.xy() for e in self.entities if e.role == "vehicle"]
        # corridors the participant must stay in (safety rules): the automatic start has to satisfy them from the first sample
        corridors = [(a["path"], float(a.get("tol", 2.0))) for t in self.tasks if t.explicit_spec for fm in t.spec_safety
                     for a in F.atoms_in(fm) if a["op"] == "near_path" and a.get("path")]
        best, best_cost = None, 1e18
        for n, d in dist.items():
            pt = pg.nodes[n]
            if self.map._m.surface_at(pt) not in ("sidewalk", "path", "ground") or d < 3:
                continue
            if any(geo.dist(pt, v) < 4.0 for v in vehicles):
                continue
            cost = abs(d - self.AUTO_USER_DISTANCE) + sum(1000.0 for pts, tol in corridors if geo.dist_to_polyline([tuple(q) for q in pts], pt) > tol - 0.3)
            if cost < best_cost:
                best, best_cost = pt, cost
        if corridors and (best is None or best_cost >= 1000.0):             # no network node inside the corridor: start at its first point
            first = tuple(corridors[0][0][0])
            if self.map._m.surface_at(first) in ("sidewalk", "path", "ground", "crosswalk"):
                best = first
        if best is None:
            return
        self.entities.insert(0, _Entity(USER, "user", "user_rig", Place(best[0], best[1], 0.0, geo.heading(best, g), None, None, None, "auto")))

    def _finalize(self) -> None:
        """Compile helper-made tasks to the specification language and derive each task's category from the formulas."""
        self._ensure_user()
        moving = self._moving()
        for t in self.tasks:
            if not t.explicit_spec:
                t.spec_goal, t.spec_safety = self._compile_legacy(t)
            t.category = category_of(task_axes(t.spec_goal, t.spec_safety, moving, self.map._m, t.kind))

    # ---------------------------------------------------------------- specification language
    def _compile_legacy(self, t: VRTask) -> tuple[dict, list]:
        """go_to / cross / follow_path express themselves in the SAME language the model may write directly."""
        q = self.map
        if t.kind == "cross" and t.target.place is not None and t.target.place.feature:
            pl = t.target.place
            raw_goal = {"op": "call", "name": "cross", "args": {"far_zone": {
                "kind": "crossing_side", "id": pl.feature, "side": "end" if (pl.u or 0.0) >= 0.5 else "start",
                "inset": 1.0, "r": t.tolerance}}}
        elif t.target.place is not None:
            p = t.target.place
            raw_goal = {"op": "call", "name": "reach", "args": {"zone": {"kind": "disc", "x": round(p.x, 3), "y": round(p.y, 3), "r": t.tolerance}}}
        elif t.target.entity:
            raw_goal = {"op": "call", "name": "reach", "args": {"zone": {"kind": "entity", "name": t.target.entity, "r": t.tolerance}}}
        else:
            raw_goal = {"op": "eventually", "arg": {"op": "true"}}
        raw_safety: list[tuple[dict, str]] = []
        for f in t.failures:
            if isinstance(f, Collision):
                for n in f.entities:
                    raw_safety.append(({"op": "call", "name": "collision_free", "args": {"entity": n, "r": 0.3}}, f"collision with {n}"))
            elif isinstance(f, SurfaceAdherence):
                raw_safety.append(({"op": "call", "name": "stay_on", "args": {"surface": f.surface}}, f"left {f.surface}"))
            elif isinstance(f, FollowTrajectory) and len(f.vertices) >= 2:
                raw_safety.append(({"op": "call", "name": "stay_near_path",
                                    "args": {"path": [[round(v.x, 3), round(v.y, 3)] for v in f.vertices], "tol": f.tolerance}}, "left the marked path"))
            elif isinstance(f, SignalViolation) and f.signal:
                raw_safety.append(({"op": "call", "name": "obey_signal", "args": {
                    "zone": {"kind": "crossing", "id": f.crossing}, "signal": f.signal}}, "crossed on red"))
            elif isinstance(f, TriggerFailure):
                for n in f.events:
                    raw_safety.append(({"op": "call", "name": "no_event", "args": {"name": n}}, f"event {n} occurred"))
        goal = F.resolve(F.prepare(raw_goal), q)
        safety = []
        for raw, reason in raw_safety:
            x = F.resolve(F.prepare(raw), q)
            x["label"] = reason                      # shown to the participant when this rule is the one that failed
            safety.append(x)
        t.spec_raw = {"goal": raw_goal, "safety": [r for r, _ in raw_safety]}
        return goal, safety

    def apply_spec(self, doc: dict, level: Optional[int] = None) -> list["TaskHandle"]:
        """Create the tasks of a specification document (see usg.spec). ``level`` 1 forbids own definitions.

        The document is DATA: it is checked and expanded, never executed. Map references (crossings, features) are
        resolved here; entity and signal references are checked by the validator once the whole scenario exists.
        """
        level = SPEC_LEVEL if level is None else level
        if not isinstance(doc, dict) or not isinstance(doc.get("tasks"), list) or not doc["tasks"]:
            raise F.SpecError("spec: needs {\"tasks\": [ {name, instruction, goal, safety?, timeout?, after?, ...} ]}")
        defs = doc.get("defs") or {}
        if defs and level < 2:
            raise F.SpecError("spec: own definitions ('defs') are not allowed at this level; use the library "
                              f"definitions {sorted(F.STD_LIB)} or plain formulas")
        F.check_defs(defs)
        handles: dict[str, TaskHandle] = {}
        out: list[TaskHandle] = []
        for i, td in enumerate(doc["tasks"]):
            where = f"tasks[{i}]"
            if not isinstance(td, dict) or not isinstance(td.get("name"), str) or "goal" not in td:
                raise F.SpecError(f"{where}: each task needs a 'name' and a 'goal' formula")
            extra = set(td) - {"name", "instruction", "success", "failure", "goal", "safety", "timeout", "after", "group",
                               "mode", "required", "start_time"}
            if extra:
                raise F.SpecError(f"{where}: unknown fields {sorted(extra)}")
            if td["name"] in handles:
                raise F.SpecError(f"{where}: duplicate task name '{td['name']}'")
            goal = F.resolve(F.prepare(td["goal"], defs, f"{where}.goal"), self.map)
            safety = [F.resolve(F.prepare(x, defs, f"{where}.safety[{j}]"), self.map) for j, x in enumerate(td.get("safety", []))]
            for x, raw in zip(safety, td.get("safety", [])):
                x["label"] = _reason(raw, x)
            to = td.get("timeout", {})
            initial = float(to.get("initial", 60.0))
            baseline = float(to.get("baseline", initial * 1.5))
            after = []
            for a in td.get("after", []):
                if a not in handles:
                    raise F.SpecError(f"{where}.after: unknown or later task '{a}' (list tasks in dependency order)")
                after.append(handles[a])
            zs = [z for z in F.zones_in(goal) if z["kind"] in ("disc", "rect")]
            if zs:
                z = zs[-1]
                place = Place(z["x"], z["y"]) if z["kind"] == "disc" else Place(z["cx"], z["cy"])
                target = Target(place=place, name=td["name"], cls="Location")
            else:
                target = Target(name=td["name"], cls="Location")
            h = self._new_task("go", td["name"], target, td.get("instruction"), td.get("success"), td.get("failure"),
                               1.5, 3.0, initial, baseline, [], after, float(td.get("start_time", 0.0)), "spec", (),
                               bool(td.get("required", True)))
            t = next(x for x in self.tasks if x.id == h.id)
            t.spec_goal, t.spec_safety, t.explicit_spec = goal, safety, True
            t.spec_raw = {"goal": td["goal"], "safety": list(td.get("safety", []))}
            if td.get("group"):
                t.group, t.mode = str(td["group"]), td.get("mode") or ("sequential" if after else "parallel")
            elif td.get("mode") in ("sequential", "parallel"):
                t.group, t.mode = f"group_{td['mode']}", td["mode"]
            handles[td["name"]] = h
            out.append(h)
        by = {x.id: x for x in self.tasks}
        for t in list(by.values()):
            if t.depends_on and t.mode == "independent" and t.group is None:   # "after" without a mode means: run in order
                for tid in [t.id] + list(t.depends_on):
                    if by[tid].group is None:
                        by[tid].group, by[tid].mode = "sequence", "sequential"
        return out

    # ================================================================ spec (for validator / tools)
    def to_spec(self) -> dict:
        self._finalize()
        def pl(p: Place) -> dict:
            return {"x": round(p.x, 3), "y": round(p.y, 3), "h": round(p.h, 4), "feature": p.feature}

        ents = [{"name": e.name, "role": e.role, "model": e.model, "start": pl(e.start),
                 "moving": e.moving, "speed": e.speed, "route": [pl(p) for p in e.route],
                 "start_when": {"kind": e.start_when.kind, "value": e.start_when.value,
                               "task": e.start_when.task}} for e in self.entities]
        tasks = []
        for t in self.tasks:
            tg = None
            if t.target.place:
                tg = pl(t.target.place)
            tasks.append({
                "id": t.id, "name": t.name, "kind": t.kind, "category": t.category,
                "target": tg, "target_entity": t.target.entity, "target_name": t.target.name,
                "instruction": t.instruction, "tolerance": t.tolerance, "max_speed": t.max_speed,
                "timeout": {"initial": t.timeout.initial, "baseline": t.timeout.baseline},
                "depends_on": t.depends_on, "group": t.group, "mode": t.mode, "start_time": t.start_time,
                "failures": [self._fspec(f) for f in t.failures],
                "evaluation": t.evaluation, "required": t.required,
                "goal": t.spec_goal, "safety": t.spec_safety, "explicit_spec": t.explicit_spec, "spec_raw": t.spec_raw})
        events = [f"task_{t.id}_{t.name}" for t in self.tasks] + [f"move_{e.name}" for e in self.entities if e.moving]
        events += [ev.name for _a, ev in self._extra_events]
        return {"name": self.name, "scenario_type": self.scenario_type, "description": self.description,
                "event_names": events,
                "entities": ents, "tasks": tasks, "horizon": self.horizon(),
                "signals": [{"signal": c.signal, "green": c.green, "red": c.red, "offset": c.offset,
                             "initial": c.initial} for c in self.cycles],
                "virtual_signals": [{"signal": n, "crossing": p.feature} for n, p in sorted(self.virtual_signals.items())]}

    @staticmethod
    def _fspec(f: FailureCondition) -> dict:
        d = {"type": type(f).__name__}
        for k, v in vars(f).items():
            if k == "vertices":
                d[k] = [{"x": p.x, "y": p.y} for p in v]
            else:
                d[k] = v
        return d

    # ================================================================ build
    def build(self, roadfile: str = "map.xodr") -> xosc.Scenario:
        self._ensure_user()
        if not any(e.role == "user" for e in self.entities):
            raise ValueError("scenario has no user: call s.user(start=...)")
        if not self.tasks:
            raise ValueError("scenario has no tasks")
        self._finalize()
        hz = self.horizon()
        ents = xosc.Entities()
        init = xosc.Init()
        for e in self.entities:
            if e.role == "vehicle":
                obj = xosc.Vehicle(e.name, xosc.VehicleCategory.bus if e.model.startswith("bus") else
                                   xosc.VehicleCategory.truck if e.model.startswith("truck") else
                                   xosc.VehicleCategory.car,
                                   xosc.BoundingBox(2.0, 4.6, 1.5, 1.4, 0, 0.75),
                                   xosc.Axle(0.5, 0.8, 1.68, 2.98, 0.4), xosc.Axle(0, 0.8, 1.68, 0, 0.4),
                                   50.0, 8.0, 10.0, model3d=e.model)
            else:
                obj = xosc.Pedestrian(e.name, 75.0, xosc.PedestrianCategory.pedestrian,
                                      xosc.BoundingBox(0.6, 0.6, 1.75, 0, 0, 0.875), model=e.model)
            obj.add_property("usg_role", e.role)
            ents.add_scenario_object(e.name, obj)
            init.add_init_action(e.name, xosc.TeleportAction(
                xosc.WorldPosition(round(e.start.x, 3), round(e.start.y, 3), 0.0, round(e.start.h, 4))))
            init.add_init_action(e.name, xosc.AbsoluteSpeedAction(
                0.0, xosc.TransitionDynamics(xosc.DynamicsShapes.step, xosc.DynamicsDimension.time, 0.0)))
        numbers = signal_numbers(self.map._m, self.virtual_signals)
        for c in self.cycles:
            init.add_global_action(xosc.TrafficSignalStateAction(str(numbers[c.signal]), self._lamps(c.signal, c.initial)))

        storyboard_stories: list[xosc.Story] = []
        user = next(e for e in self.entities if e.role == "user")

        # ---- user tasks: ONE maneuver, one event per task, dependencies expressed as triggers
        mnv = xosc.Maneuver("UserTasks")
        for t in self.tasks:
            ev = xosc.Event(f"task_{t.id}_{t.name}", xosc.Priority.override)
            ev.add_action("vr_task", task_action(t))
            ev.add_trigger(self._task_trigger(t))
            mnv.add_event(ev)
        mg = xosc.ManeuverGroup("UserTaskGroup")
        mg.add_actor(user.name)
        mg.add_maneuver(mnv)
        act = xosc.Act("UserTaskAct", self._time_trigger("ActStart", 0.0))
        act.add_maneuver_group(mg)
        st = xosc.Story("UserTaskStory")
        st.add_act(act)
        storyboard_stories.append(st)

        # ---- NPC movement
        for e in self.entities:
            if not e.moving:
                continue
            ev = xosc.Event(f"move_{e.name}", xosc.Priority.override)
            times, pos, acc = [], [], 0.0
            pts = [e.start] + e.route
            for i, p in enumerate(pts):
                if i:
                    acc += pts[i - 1].dist(p) / max(e.speed, 0.1)
                times.append(round(acc, 3))
                pos.append(xosc.WorldPosition(round(p.x, 3), round(p.y, 3), 0.0, round(p.h, 4)))
            traj = xosc.Trajectory(f"route_{e.name}", False)
            traj.add_shape(xosc.Polyline(times, pos))
            ev.add_action("speed", xosc.AbsoluteSpeedAction(
                e.speed, xosc.TransitionDynamics(xosc.DynamicsShapes.step, xosc.DynamicsDimension.time, 0.0)))
            ev.add_action("route", xosc.FollowTrajectoryAction(
                traj, xosc.FollowingMode.position, "relative", 1.0, 0.0))
            ev.add_trigger(self._npc_trigger(e))
            m2 = xosc.Maneuver(f"Move_{e.name}")
            m2.add_event(ev)
            g2 = xosc.ManeuverGroup(f"MoveGroup_{e.name}")
            g2.add_actor(e.name)
            g2.add_maneuver(m2)
            a2 = xosc.Act(f"MoveAct_{e.name}", self._time_trigger("ActStart", 0.0))
            a2.add_maneuver_group(g2)
            s2 = xosc.Story(f"MoveStory_{e.name}")
            s2.add_act(a2)
            storyboard_stories.append(s2)

        # ---- signals
        if self.cycles:
            m3 = xosc.Maneuver("Signals")
            for c in self.cycles:
                state = c.initial
                t = c.offset + (c.red if state == "red" else c.green)
                k = 0
                while t < hz:
                    state = "green" if state == "red" else "red"
                    ev = xosc.Event(f"sig_{c.signal}_{k}", xosc.Priority.parallel)
                    ev.add_action("set", xosc.TrafficSignalStateAction(str(numbers[c.signal]), self._lamps(c.signal, state)))
                    ev.add_trigger(self._time_trigger(f"SigT{k}_{c.signal}", t))
                    m3.add_event(ev)
                    t += c.green if state == "green" else c.red
                    k += 1
            g3 = xosc.ManeuverGroup("SignalGroup")
            g3.add_actor(user.name)
            g3.add_maneuver(m3)
            a3 = xosc.Act("SignalAct", self._time_trigger("ActStart", 0.0))
            a3.add_maneuver_group(g3)
            s3 = xosc.Story("SignalStory")
            s3.add_act(a3)
            storyboard_stories.append(s3)

        # ---- raw events from the escape hatch
        for actor, ev in self._extra_events:
            m4 = xosc.Maneuver(f"Extra_{ev.name}")
            m4.add_event(ev)
            g4 = xosc.ManeuverGroup(f"ExtraGroup_{ev.name}")
            g4.add_actor(actor)
            g4.add_maneuver(m4)
            a4 = xosc.Act(f"ExtraAct_{ev.name}", self._time_trigger("ActStart", 0.0))
            a4.add_maneuver_group(g4)
            s4 = xosc.Story(f"ExtraStory_{ev.name}")
            s4.add_act(a4)
            storyboard_stories.append(s4)

        stop = xosc.ValueTrigger("StopCondition", 0, xosc.ConditionEdge.rising,
                                 xosc.SimulationTimeCondition(hz, xosc.Rule.greaterThan),
                                 triggeringpoint="stop")
        sb = xosc.StoryBoard(init, stop)
        for s in storyboard_stories:
            sb.add_story(s)

        props = xosc.Properties()
        props.add_property("usg_scenario_type", self.scenario_type or "")
        props.add_property("usg_description", self.description)
        pdecl = xosc.ParameterDeclarations()
        for sig_name, number in sorted(numbers.items(), key=lambda kv: kv[1]):          # symbolic signal name -> numeric id (for the player); string-typed like esmini's own traffic-light example
            if any(c.signal == sig_name for c in self.cycles):
                pdecl.add_parameter(xosc.Parameter(sig_name, xosc.ParameterType.string, str(number)))
        sc = xosc.Scenario(self.name, self.author, pdecl, ents, sb,
                           xosc.RoadNetwork(roadfile=roadfile), xosc.Catalog(), header_properties=props)
        return sc

    # ---------------------------------------------------------------- triggers
    @staticmethod
    def _time_trigger(name: str, t: float) -> xosc.ValueTrigger:
        return xosc.ValueTrigger(name, 0, xosc.ConditionEdge.none,
                                 xosc.SimulationTimeCondition(float(t), xosc.Rule.greaterOrEqual))

    def _task_trigger(self, t: VRTask) -> xosc.Trigger:
        trig = xosc.Trigger("start")
        grp = xosc.ConditionGroup("start")
        grp.add_condition(xosc.ValueTrigger(f"T{t.id}Time", 0, xosc.ConditionEdge.none,
                                            xosc.SimulationTimeCondition(float(t.start_time), xosc.Rule.greaterOrEqual)))
        by = {x.id: x for x in self.tasks}
        for d in t.depends_on:
            grp.add_condition(xosc.ValueTrigger(
                f"T{t.id}After{d}", 0, xosc.ConditionEdge.none,
                xosc.StoryboardElementStateCondition(xosc.StoryboardElementType.event,
                                                     f"task_{d}_{by[d].name}",
                                                     xosc.StoryboardElementState.endTransition)))
        trig.add_conditiongroup(grp)
        return trig

    def _npc_trigger(self, e: _Entity):
        w = e.start_when
        if w.kind == "time":
            return self._time_trigger(f"{e.name}Start", w.value)
        if w.kind == "user_within":
            return xosc.EntityTrigger(f"{e.name}Start", 0, xosc.ConditionEdge.none,
                                      xosc.RelativeDistanceCondition(w.value, xosc.Rule.lessThan,
                                                                     xosc.RelativeDistanceType.euclidianDistance,
                                                                     USER, freespace=False),
                                      e.name)
        by = {x.id: x for x in self.tasks}
        tk = by[w.task]
        state = (xosc.StoryboardElementState.startTransition if w.kind == "task_started"
                 else xosc.StoryboardElementState.endTransition)
        return xosc.ValueTrigger(f"{e.name}Start", 0, xosc.ConditionEdge.none,
                                 xosc.StoryboardElementStateCondition(xosc.StoryboardElementType.event,
                                                                      f"task_{tk.id}_{tk.name}", state))

    # ================================================================ output
    def to_xml_string(self, roadfile: str = "map.xodr") -> str:
        import xml.etree.ElementTree as ET
        sc = self.build(roadfile)
        root = sc.get_element()
        ET.indent(root)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")

    def write(self, path: Union[str, Path], roadfile: str = "map.xodr") -> None:
        Path(path).write_text(self.to_xml_string(roadfile), encoding="utf-8")
