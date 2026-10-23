"""Map-aware semantic validator. Errors block a script; warnings are advice.

Messages are written for an LLM to act on: they say what is wrong, the numbers, and what to change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

from . import geo
from .mapmodel import MapModel, PED_INFRA
from .spec import formula as F

WALK_SPEED = 1.2           # m/s assumed typical VR walking speed
MAX_HUD = 160


@dataclass
class Issue:
    severity: str          # error | warning
    code: str
    message: str
    ref: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _p(d: Optional[dict]) -> Optional[tuple[float, float]]:
    return None if not d else (d["x"], d["y"])


def _on_road(m: MapModel, p: tuple[float, float]) -> bool:
    """Road or crosswalk, with a small tolerance so a lane centre on a narrow road is not rejected by rounding."""
    surf = m.surface_at(p)
    if surf in ("road", "crosswalk"):
        return True
    if surf in ("building", "water"):
        return False
    rd, _, _, d = m.nearest_road(p)
    return rd is not None and d <= rd.width / 2 + 0.3


def _road_hint(m: MapModel, p: tuple[float, float]) -> str:
    rd, _, _, d = m.nearest_road(p)
    if rd is None:
        return "there is no road nearby"
    return (f"the nearest road is {rd.id} ('{rd.name or rd.hclass}', {'one-way, ' if rd.oneway else ''}{rd.width:.1f} m wide) "
            f"and the point is {d:.1f} m from its centre-line")


def validate(spec: dict, m: MapModel, margins: Optional[dict] = None) -> list[Issue]:
    out: list[Issue] = []

    def err(code, msg, ref=None):
        out.append(Issue("error", code, msg, ref))

    def warn(code, msg, ref=None):
        out.append(Issue("warning", code, msg, ref))

    ents = {e["name"]: e for e in spec["entities"]}
    tasks = {t["id"]: t for t in spec["tasks"]}
    user = next((e for e in spec["entities"] if e["role"] == "user"), None)
    if user is None:
        err("no_user", "scenario has no user; call s.user(start=...)")
        return out
    if not tasks:
        err("no_tasks", "scenario has no tasks")
        return out

    # ---------------------------------------------------------------- entities
    for e in spec["entities"]:
        sp = _p(e["start"])
        surf = m.surface_at(sp)
        if e["role"] in ("user", "walker") and surf not in PED_INFRA | {"ground"}:
            err("bad_start_surface", f"{e['name']} starts on '{surf}' at ({sp[0]:.1f},{sp[1]:.1f}); "
                f"pedestrians must start on a sidewalk, crosswalk, path or open ground", e["name"])
        if e["role"] == "vehicle":
            if not _on_road(m, sp):
                err("vehicle_off_road", f"{e['name']} starts on '{surf}' at ({sp[0]:.1f},{sp[1]:.1f}); {_road_hint(m, sp)}. "
                    f"Vehicles must start on a road: use MAP.drive_route(road_id, s_from, s_to, 'forward') on a wider two-way road, "
                    f"or MAP.kerb_slots(...)", e["name"])
            for i, r in enumerate(e["route"]):
                if not _on_road(m, _p(r)):
                    pt = _p(r)
                    err("vehicle_route_off_road", f"{e['name']} route point {i} at ({pt[0]:.1f},{pt[1]:.1f}) is on '{m.surface_at(pt)}', not on the road; "
                        f"{_road_hint(m, pt)}. Build routes with MAP.drive_route(road_id, s_from, s_to, 'forward'); if this road is too narrow "
                        f"or one-way, choose a crossing on a different road (list_features kind=crossing, then MAP.road(road_id))", e["name"])
                    break
            if e["moving"]:
                rd, _, _, d = m.nearest_road(sp)
                if rd and e["speed"] > rd.speed * 1.6 + 1:
                    warn("vehicle_too_fast", f"{e['name']} speed {e['speed']:.1f} m/s vs limit {rd.speed:.1f} m/s on {rd.id}", e["name"])
                if e["speed"] <= 0.1:
                    err("vehicle_speed", f"{e['name']} has a route but speed ~0", e["name"])
        if e["role"] == "walker" and e["moving"] and not 0.4 <= e["speed"] <= 2.5:
            warn("walker_speed", f"{e['name']} speed {e['speed']:.1f} m/s is not plausible for walking (0.4-2.5)", e["name"])
    parked = [e for e in spec["entities"] if e["role"] == "vehicle" and not e["moving"]]
    for i, a in enumerate(parked):
        if geo.dist(_p(a["start"]), _p(user["start"])) < 2.5:
            err("parked_on_user", f"{a['name']} is parked within 2.5 m of the user's start", a["name"])
        for b in parked[i + 1:]:
            if geo.dist(_p(a["start"]), _p(b["start"])) < 4.0:
                warn("parked_overlap", f"{a['name']} and {b['name']} overlap (<4 m apart)", a["name"])

    # ---------------------------------------------------------------- tasks
    done_pos: dict[int, tuple[float, float]] = {}
    signals_defined = {c["signal"] for c in spec["signals"]}
    for t in sorted(spec["tasks"], key=lambda t: t["id"]):
        ref = f"task_{t['id']}"
        tgt = _p(t["target"])
        if tgt is None and not t["target_entity"]:
            if not t.get("explicit_spec"):
                err("task_no_target", f"task {t['id']} has no target", ref)
            continue                                   # a pure spec task (e.g. only "look") has no zone to route to
        for d in t["depends_on"]:
            if d not in tasks:
                err("bad_dependency", f"task {t['id']} depends on unknown task {d}", ref)
            elif d >= t["id"]:
                err("dependency_order", f"task {t['id']} depends on later task {d}; create tasks in dependency order", ref)
        if not t["instruction"].get("en"):
            err("no_instruction", f"task {t['id']} has no English instruction text", ref)
        elif len(t["instruction"]["en"]) > MAX_HUD:
            warn("long_instruction", f"task {t['id']} instruction is {len(t['instruction']['en'])} chars; keep HUD text <= {MAX_HUD}", ref)
        to = t["timeout"]
        if to["baseline"] < to["initial"]:
            err("timeout_order", f"task {t['id']}: baseline timeout ({to['baseline']}) must be >= initial ({to['initial']})", ref)
        if t["tolerance"] < 0.5 or t["tolerance"] > 5:
            warn("tolerance", f"task {t['id']} tolerance {t['tolerance']} m is unusual (0.5-5)", ref)
        if tgt is None:
            continue
        surf = m.surface_at(tgt)
        if surf in ("building", "water"):
            err("target_unreachable", f"task {t['id']} target ({tgt[0]:.1f},{tgt[1]:.1f}) is inside a {surf}", ref)
            continue
        if t["kind"] == "go" and t["category"] == "ptp_env" and surf == "road":
            err("target_on_road", f"task {t['id']} is 'ptp_env' but its target is on the road; use a sidewalk/path target or MAP.along_road for road tasks", ref)
        if t["category"] == "ptp_road" and surf not in ("road", "crosswalk"):
            err("target_not_on_road", f"task {t['id']} is a road task but its target is on '{surf}'", ref)

        # start of this task = previous dependency's target, else user's start
        origin = _p(user["start"])
        if t["depends_on"]:
            dep = max(t["depends_on"])
            origin = done_pos.get(dep, origin)
        done_pos[t["id"]] = tgt

        # reachability + timeout feasibility
        r = m.ped_graph.route(origin, tgt)
        if r is None:
            err("no_route", f"task {t['id']}: no pedestrian route from ({origin[0]:.0f},{origin[1]:.0f}) to ({tgt[0]:.0f},{tgt[1]:.0f}) "
                f"(blocked by rail/water/gaps)", ref)
        else:
            need = r["length"] / WALK_SPEED
            if t["kind"] == "go" and t["category"] == "ptp_road":
                need = geo.dist(origin, tgt) / WALK_SPEED
            if to["initial"] < need * 1.15 + 3:
                err("timeout_too_short", f"task {t['id']}: route is {r['length']:.0f} m (~{need:.0f} s at {WALK_SPEED} m/s) "
                    f"but initial timeout is {to['initial']:.0f} s; use >= {math.ceil(need * 1.5 + 5)}", ref)
            elif to["baseline"] > max(240, need * 8):
                warn("timeout_long", f"task {t['id']} baseline timeout {to['baseline']:.0f}s is very long for a {r['length']:.0f} m route", ref)
        if t["kind"] == "cross":
            cname = t["target_name"]
            c = m.get(cname)
            if c is None or c.kind != "crossing":
                err("cross_unknown", f"task {t['id']}: '{cname}' is not a crossing id", ref)
            else:
                a, b = c.endpoints()
                near = min(geo.dist(origin, a), geo.dist(origin, b))
                if near > 25:
                    warn("far_from_crossing", f"task {t['id']}: the user starts {near:.0f} m from {cname}; "
                         f"add a go_to task first or move the start with MAP.crossing_side()", ref)

        # failures
        for f in t["failures"]:
            ft = f["type"]
            if ft == "Collision":
                for n in f["entities"]:
                    if n not in ents:
                        err("unknown_entity", f"task {t['id']} collision entity '{n}' does not exist", ref)
            elif ft == "SignalViolation":
                if f["signal"] not in signals_defined:
                    err("signal_not_cycled", f"task {t['id']} obeys signal '{f['signal']}' but no signal_cycle() exists for it; "
                        f"call s.signal_cycle('{f['crossing']}', green=..., red=...)", ref)
            elif ft == "FollowTrajectory":
                bad = [v for v in f["vertices"] if m.surface_at((v["x"], v["y"])) in ("building", "water")]
                if bad:
                    err("trajectory_blocked", f"task {t['id']} path has {len(bad)} vertices inside buildings/water", ref)
                if f["tolerance"] < 0.8:
                    warn("corridor_narrow", f"task {t['id']} corridor {f['tolerance']} m is very tight for VR walking", ref)

    out.extend(_check_specs(spec, m, ents, signals_defined, user, margins))

    # groups
    for name in {t["group"] for t in spec["tasks"] if t["group"]}:
        g = [t for t in spec["tasks"] if t["group"] == name]
        if g[0]["mode"] == "sequential" and len(g) > 1 and not all(
                any(d in {x["id"] for x in g} for d in t["depends_on"]) for t in g[1:]):
            err("group_not_chained", f"group '{name}' is sequential but tasks are not chained; use s.sequence([...])")

    # horizon
    if spec["horizon"] > 900:
        warn("long_scenario", f"scenario horizon is {spec['horizon']:.0f}s; VR sessions are best under ~10 minutes")

    out.extend(check_archetype(spec, m))
    return out


# ================================================================ specification (formula) rules
def _check_specs(spec: dict, m: MapModel, ents: dict, signals: set, user: dict, margins: Optional[dict]) -> list[Issue]:
    out: list[Issue] = []
    names = set(spec.get("event_names", []))
    for t in spec["tasks"]:
        if "goal" not in t or t["goal"] is None:
            continue
        ref = f"task_{t['id']}"
        who = f"task {t['id']} ({t['name']})"
        fms = [t["goal"]] + list(t["safety"])
        for f in fms:
            for n in sorted(F.entities_in(f)):
                if n not in ents or ents[n]["role"] == "user":
                    out.append(Issue("error", "spec_unknown_entity",
                                     f"{who}: the formula refers to entity '{n}' which does not exist; entities are {sorted(k for k, e in ents.items() if e['role'] != 'user')}. "
                                     f"Create it in the script (vehicle/walker/parked_vehicle) or fix the name", ref))
            for sg in sorted(F.signals_in(f)):
                if sg not in signals:
                    out.append(Issue("error", "spec_unknown_signal",
                                     f"{who}: the formula uses signal '{sg}' but no signal_cycle() defines it; call scenario.signal_cycle('<crossing id>', green=.., red=..) "
                                     f"(signals defined: {sorted(signals)})", ref))
            for ev in sorted(F.events_in(f)):
                if ev not in names and not ev.startswith("sig_"):
                    out.append(Issue("warning", "spec_unknown_event", f"{who}: no storyboard event is called '{ev}' (events: {sorted(names)[:8]})", ref))
            for z in F.zones_in(f):
                if z["kind"] == "disc":
                    surf = m.surface_at((z["x"], z["y"]))
                    if surf in ("building", "water"):
                        out.append(Issue("error", "spec_zone_unreachable", f"{who}: a zone centred at ({z['x']:.1f},{z['y']:.1f}) is inside a {surf}", ref))
            for n in F.walk(f):
                if n["op"] in ("eventually", "always", "until") and n.get("end") is not None and n["end"] > t["timeout"]["baseline"]:
                    out.append(Issue("warning", "spec_window_beyond_timeout",
                                     f"{who}: a time window ends at {n['end']:g} s but the baseline timeout is {t['timeout']['baseline']:g} s, so it can never complete", ref))
        # moving obstacles must come near the user's path, otherwise there is nothing to keep clear of
        tgt = _p(t["target"])
        if tgt is not None:
            a = _p(user["start"])
            for f in fms:
                for n in F.atoms_in(f):
                    e = ents.get(n.get("entity", ""))
                    if n["op"] == "dist_ge" and e and e["moving"]:
                        pts = [(e["start"]["x"], e["start"]["y"])] + [(r["x"], r["y"]) for r in e["route"]]
                        if all(geo.dist_to_polyline(pts, (a[0] + (tgt[0] - a[0]) * k / 10, a[1] + (tgt[1] - a[1]) * k / 10)) >= 6.0 for k in range(11)):
                            out.append(Issue("warning", "spec_mover_no_conflict",
                                             f"{who}: the moving entity '{n['entity']}' never comes within 6 m of the user's path, so keeping clear of it is trivial", ref))
        mg = (margins or {}).get(t["id"])
        if mg is not None and not mg["ok"]:
            bad = []
            if mg["goal"] < 0:
                bad.append(f"the goal margin is {mg['goal']:.2f}")
            if mg["min_safety"] is not None and mg["min_safety"] < 0:
                bad.append(f"a safety margin is {mg['min_safety']:.2f}")
            hard = bool(t.get("explicit_spec")) and mg["min_safety"] is not None and mg["min_safety"] < 0
            out.append(Issue("error" if hard else "warning", "spec_rule_violated_by_nominal" if hard else "spec_nominal",
                             f"{who}: a nominal walker (walks the route, waits for green, keeps gaze on look targets) does not satisfy the specification: "
                             f"{'; '.join(bad)}. Check the zones, time windows and timeouts" +
                             ("; a safety rule you wrote is broken by an ordinary walk from the start to the goal, so it contradicts the task (for example a rule "
                              "that keeps the participant on the road while the start is on the sidewalk)" if hard else ""), ref))
    return out


# ================================================================ archetype rules
def check_archetype(spec: dict, m: MapModel) -> list[Issue]:
    from .scenario_types import ARCHETYPES
    st = spec.get("scenario_type")
    if not st:
        return [Issue("warning", "no_scenario_type", "scenario_type not set; pass scenario_type=... to ScenarioBuilder")]
    if st == "custom":                                     # a free combination of constraints: no named point to check
        return []
    a = ARCHETYPES.get(st)
    if a is None:
        return [Issue("error", "unknown_scenario_type", f"unknown scenario_type '{st}', choose from {sorted(ARCHETYPES)} or 'custom'")]
    return [Issue(sev, code, msg) for sev, code, msg in a["check"](spec, m)]
