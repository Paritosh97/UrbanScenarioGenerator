"""The 7 pedestrian scenario archetypes the whole system is built around.

Each archetype has: a description for the agent, required elements, a map-adaptive reference
script (``usg/scenarios/<id>.py``, also used as the few-shot example) and a rule checker.
Mapping to the paper's task taxonomy:

  ptp_env, ptp_road, cpath, env_con, dyn_nav  -> the five navigation task categories
  dep_comp, indep_comp                        -> the two composite (multi-task) scenarios

The same taxonomy seen as CONSTRAINT AXES (see ``AXES``): every task is "reach a target" plus constraints on the
surface, the path, static obstacles, moving obstacles, a traffic signal, and how several tasks are composed. Each
archetype is a named point on those axes; ``axes_of`` reports where a concrete scenario sits (it may combine several).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import geo
from .mapmodel import PED_INFRA

_DIR = Path(__file__).parent / "scenarios"


def _tasks(spec, cat=None):
    return [t for t in spec["tasks"] if cat is None or t["category"] == cat]


def _atoms(t):
    """All atoms of a task's goal and safety formulas (every task carries them; see usg.spec)."""
    from .spec import formula as F
    return [a for f in [t["goal"]] + list(t["safety"]) for a in F.atoms_in(f)]


def _keep_clear(t):
    """Entities this task must stay away from: dist_ge atoms (collision_free / keep_clear)."""
    return {a["entity"] for a in _atoms(t) if a["op"] == "dist_ge"}


def _check_ptp_env(spec, m):
    out = []
    ts = _tasks(spec, "ptp_env")
    if not ts:
        out.append(("error", "arch_ptp_env", "ptp_env needs a go_to task whose target is on a sidewalk/path/open ground "
                    "and with no Collision/FollowTrajectory/SurfaceAdherence failure"))
        return out
    user = next(e for e in spec["entities"] if e["role"] == "user")
    for t in ts:
        if t["target"] is None:
            continue
        r = m.ped_graph.route((user["start"]["x"], user["start"]["y"]), (t["target"]["x"], t["target"]["y"]))
        if r and r["crossings"]:
            out.append(("warning", "arch_ptp_env_crosses", f"task {t['id']}: the route uses crossing(s) {r['crossings']}; "
                        f"environment navigation should stay on one side of the road (pick a nearer target)"))
    return out


def _check_ptp_road(spec, m):
    if not _tasks(spec, "ptp_road"):
        return [("error", "arch_ptp_road", "ptp_road needs a go_to task whose target point lies ON the road surface "
                 "(e.g. MAP.along_road(road_id, s)); check the target's surface is 'road'")]
    return []


def _check_cpath(spec, m):
    if not any(a["op"] in ("near_path", "on_surface") for t in spec["tasks"] for a in _atoms(t)):
        return [("error", "arch_cpath", "cpath needs a task with a path constraint: use scenario.follow_path([...]) or "
                 "go_to(..., on_surface='pedestrian_infra')")]
    return []


def _check_env_con(spec, m):
    out = []
    parked = [e for e in spec["entities"] if e["role"] == "vehicle" and not e["moving"]]
    if len(parked) < 2:
        out.append(("error", "arch_env_con_obstacles", f"env_con needs >=2 static obstacles (parked_vehicle); found {len(parked)}"))
    names = {e["name"] for e in parked}
    if not any(_keep_clear(t) & names for t in spec["tasks"]):
        out.append(("error", "arch_env_con_collision", "env_con needs a task with avoid=[parked vehicle names] "
                    "so touching an obstacle fails the task"))
    if any(e["moving"] for e in spec["entities"] if e["role"] == "vehicle"):
        out.append(("warning", "arch_env_con_moving", "moving vehicles make this a dyn_nav scenario"))
    return out


def _check_dyn_nav(spec, m):
    out = []
    movers = {e["name"]: e for e in spec["entities"] if e["moving"]}
    if not movers:
        return [("error", "arch_dyn_nav_mover", "dyn_nav needs at least one moving vehicle/walker (route + speed)")]
    coll = [(t, _keep_clear(t) & set(movers)) for t in spec["tasks"] if _keep_clear(t) & set(movers)]
    if not coll:
        out.append(("error", "arch_dyn_nav_collision", "dyn_nav needs a task with avoid=[moving entity name]"))
        return out
    for t, names in coll:
        if t["target"] is None:
            continue
        user = next(e for e in spec["entities"] if e["role"] == "user")
        a = (user["start"]["x"], user["start"]["y"])
        b = (t["target"]["x"], t["target"]["y"])
        ok = False
        for n in names:
            pts = [(movers[n]["start"]["x"], movers[n]["start"]["y"])] + [(p["x"], p["y"]) for p in movers[n]["route"]]
            for k in range(0, 11):
                q = (a[0] + (b[0] - a[0]) * k / 10, a[1] + (b[1] - a[1]) * k / 10)
                if geo.dist_to_polyline(pts, q) < 6.0:
                    ok = True
        if not ok:
            out.append(("warning", "arch_dyn_nav_no_conflict", f"task {t['id']}: the moving entity's route never comes within "
                        f"6 m of the user's path, so there is nothing to react to"))
    return out


def _check_dep_comp(spec, m):
    seq = [t for t in spec["tasks"] if t["mode"] == "sequential"]
    if len(seq) < 2:
        return [("error", "arch_dep_comp", "dep_comp needs >=2 tasks chained with scenario.sequence([t1, t2, ...])")]
    return []


def _check_indep_comp(spec, m):
    par = [t for t in spec["tasks"] if t["mode"] == "parallel"]
    out = []
    if len(par) < 2:
        out.append(("error", "arch_indep_comp", "indep_comp needs >=2 tasks grouped with scenario.parallel([t1, t2, ...])"))
    ids = {t["id"] for t in par}
    if any(set(t["depends_on"]) & ids for t in par):
        out.append(("error", "arch_indep_deps", "parallel tasks must not depend on each other"))
    return out


# ------------------------------------------------------------------ the constraint axes
# Every task is "reach a target" plus constraints on a few axes. The 7 archetypes are NAMED POINTS on those axes
# (everything else at its default); a real scenario may combine several constraints. The axes of a concrete scenario are
# DERIVED from its task formulas (``usg.spec.axes``), not from hand-written per-type rules.
from .spec.axes import AXES, AXIS_DEFAULTS, scenario_axes  # noqa: E402


def _axes(**over: str) -> dict[str, str]:
    return {**AXIS_DEFAULTS, **over}


def axes_of(spec: dict, m) -> dict[str, str]:
    """Where a concrete scenario sits on the constraint axes (spec = ScenarioBuilder.to_spec(), m = MapModel)."""
    moving = {e["name"] for e in spec["entities"] if e.get("moving")}
    return scenario_axes(spec["tasks"], moving, m)


def axes_label(ax: dict[str, str]) -> str:
    """Compact human-readable form that lists only the non-default axes, e.g. 'surface=crossing, dynamic=movers'."""
    parts = [f"{k}={v}" for k, v in ax.items() if v != AXIS_DEFAULTS[k]]
    return ", ".join(parts) or "base task (reach a target)"


def _entry(id_: str, title: str, desc: str, reqs: list[str], keywords: list[str], check: Callable,
           axes: dict[str, str]):
    return {"id": id_, "title": title, "description": desc, "requirements": reqs, "keywords": keywords,
            "check": check, "axes": axes, "template": (_DIR / f"{id_}.py").read_text(encoding="utf-8")}


ARCHETYPES: dict[str, dict] = {a["id"]: a for a in [
    _entry("ptp_env", "Point-to-point environment navigation",
           "Reach a target location via walkable areas (sidewalks, paths). Success: target reached before timeout. "
           "Failure: timeout.",
           ["one go_to task", "target on sidewalk/path/ground (not road)", "no obstacle/path constraints"],
           ["go to", "walk to", "reach", "find the", "bus stop", "destination", "sidewalk"], _check_ptp_env,
           _axes(surface="walkable")),
    _entry("ptp_road", "Point-to-point road navigation",
           "Reach a target location that is on the road surface. Success: target reached before timeout. Failure: timeout.",
           ["one go_to task", "target ON the carriageway (surface 'road')"],
           ["on the road", "stand on the road", "middle of the road", "road surface", "carriageway"], _check_ptp_road,
           _axes(surface="road")),
    _entry("cpath", "Constrained path navigation",
           "Navigate using only a permitted path. Success: destination reached compliantly. Failure: leaving the path or timeout.",
           ["follow_path(...) with corridor, or go_to(on_surface=...)", "FollowTrajectory or SurfaceAdherence failure"],
           ["stay on", "follow the path", "marked path", "corridor", "only use", "stay inside", "stay within"], _check_cpath,
           _axes(path="corridor")),
    _entry("env_con", "Environmentally constrained navigation",
           "Avoid STATIC obstacles (parked cars, etc.). Success: target reached without collision. Failure: collision or timeout.",
           [">=2 parked_vehicle obstacles", "a task with avoid=[obstacle names]"],
           ["parked", "obstacle", "avoid the", "between the cars", "gap", "without touching"], _check_env_con,
           _axes(static="obstacles")),
    _entry("dyn_nav", "Dynamic navigation",
           "Adapt to DYNAMIC obstacles (moving vehicles/pedestrians). Success: arrival after re-timing/re-routing. "
           "Failure: collision or timeout.",
           [">=1 moving vehicle or walker with a route", "a task with avoid=[moving entity]", "the mover's route meets the user's path"],
           ["approach", "moving", "traffic", "a car", "oncoming", "vehicle", "drives", "avoid the car", "cyclist", "being hit",
            "speeding", "bus comes"], _check_dyn_nav, _axes(dynamic="movers")),
    _entry("dep_comp", "Dependent composite tasks",
           "Several tasks that must be completed in a given ORDER. Success/failure is evaluated over the group.",
           [">=2 tasks", "scenario.sequence([...])"],
           ["then", "after that", "first", "finally", "in order", "next", "followed by"], _check_dep_comp,
           _axes(composition="ordered")),
    _entry("indep_comp", "Independent composite tasks",
           "Several independent tasks that can be completed in ANY order, concurrently active.",
           [">=2 tasks", "scenario.parallel([...])", "no dependencies between them"],
           ["any order", "both", "either", "and also", "all of", "in any order", "each of"], _check_indep_comp,
           _axes(composition="unordered")),
]}


def classify(prompt: str) -> list[str]:
    """Cheap keyword pre-classification (a hint only; the agent decides)."""
    p = prompt.lower()
    scored = sorted(((sum(k in p for k in a["keywords"]), i) for i, a in ARCHETYPES.items()), reverse=True)
    return [i for s, i in scored if s > 0] or ["ptp_env"]
