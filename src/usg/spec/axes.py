"""Constraint axes DERIVED from a task's formulas (no hand-written per-type rules).

The taxonomy of the paper is "reach a target" plus constraints on a few axes (surface, path, static obstacles, moving
obstacles, signal) and a composition axis over several tasks. Here each axis is read off the formulas themselves.
"""
from __future__ import annotations

from . import formula as F

AXES: dict[str, tuple[str, ...]] = {
    "surface": ("walkable", "road", "crossing"),        # what the goal zone stands on
    "path": ("free", "corridor"),                       # near_path / on_surface constraints present
    "static": ("none", "obstacles"),                    # keep clear of non-moving entities
    "dynamic": ("none", "movers"),                      # keep clear of moving entities
    "signal": ("none", "obeyed"),                       # a signal state is part of the specification
    "composition": ("single", "ordered", "unordered"),  # several tasks chained / grouped in parallel
}
AXIS_DEFAULTS: dict[str, str] = {k: v[0] for k, v in AXES.items()}
_RANK = {"surface": ("walkable", "crossing", "road")}


def surface_of_goal(goal: dict, m, kind: str = "go") -> str:
    """'road' | 'crossing' | 'walkable' for the goal zones of a task (most constrained wins)."""
    found = ["crossing"] if kind == "cross" else []
    for z in F.zones_in(goal):
        if z["kind"] == "rect":
            found.append("crossing")
        elif z["kind"] == "disc":
            s = m.surface_at((z["x"], z["y"]))
            found.append("road" if s == "road" else "crossing" if s == "crosswalk" else "walkable")
        else:
            found.append("walkable")
    for pick in ("road", "crossing", "walkable"):
        if pick in found:
            return pick
    return "walkable"


def task_axes(goal: dict, safety: list[dict], moving: set[str], m, kind: str = "go") -> dict[str, str]:
    ax = dict(AXIS_DEFAULTS)
    ax["surface"] = surface_of_goal(goal, m, kind)
    for fm in [goal] + list(safety):
        for a in F.atoms_in(fm):
            op = a["op"]
            if op in ("near_path", "on_surface"):
                ax["path"] = "corridor"
            elif op == "dist_ge":
                ax["dynamic" if a["entity"] in moving else "static"] = "movers" if a["entity"] in moving else "obstacles"
            elif op == "signal_is":
                ax["signal"] = "obeyed"
    return ax


def category_of(ax: dict[str, str]) -> str:
    """The taxonomy category name used in the OpenSCENARIO file (legacy precedence: path > dynamic > static > road > env)."""
    if ax["path"] == "corridor":
        return "constrained_path"
    if ax["dynamic"] == "movers":
        return "dynamic"
    if ax["static"] == "obstacles":
        return "env_constrained"
    if ax["surface"] == "road":
        return "ptp_road"
    return "ptp_env"


def scenario_axes(tasks: list[dict], moving: set[str], m) -> dict[str, str]:
    """Axes of a whole scenario (tasks are spec dicts with 'goal', 'safety', 'kind', 'mode')."""
    ax = dict(AXIS_DEFAULTS)
    surfaces = []
    for t in tasks:
        a = task_axes(t["goal"], t["safety"], moving, m, t.get("kind", "go"))
        surfaces.append(a["surface"])
        for k in ("path", "static", "dynamic", "signal"):
            if a[k] != AXIS_DEFAULTS[k]:
                ax[k] = a[k]
    for pick in ("road", "crossing", "walkable"):
        if pick in surfaces:
            ax["surface"] = pick
            break
    if sum(t["mode"] == "sequential" for t in tasks) >= 2:
        ax["composition"] = "ordered"
    elif composition_unordered(tasks):
        ax["composition"] = "unordered"
    return ax


def _reach_zones(goal) -> list[str]:
    """Zones of a goal of the form and(eventually in_zone A, eventually in_zone B, ...): several places to reach, in any order."""
    if not isinstance(goal, dict) or goal.get("op") != "and":
        return []
    zones = []
    for a in goal.get("args", []):
        if not (isinstance(a, dict) and a.get("op") == "eventually" and isinstance(a.get("arg"), dict) and a["arg"].get("op") == "in_zone"):
            return []
        zones.append(repr(sorted((a["arg"].get("zone") or {}).items(), key=str)))
    return zones


def composition_unordered(tasks: list[dict]) -> bool:
    """Several things to do in any order. Three equivalent ways to write it: tasks marked parallel; two or more tasks that are active together
    (none waits for another one); or one task whose goal is a conjunction of 'eventually reach' for different zones."""
    if sum(t.get("mode") == "parallel" for t in tasks) >= 2:
        return True
    if len(tasks) >= 2 and len({t.get("name") for t in tasks}) == len(tasks) and not any(t.get("depends_on") for t in tasks) and all(t.get("mode") != "sequential" for t in tasks) \
            and all(not t.get("start_time") for t in tasks):
        return True
    return any(len(set(_reach_zones(t.get("goal")))) >= 2 for t in tasks)
