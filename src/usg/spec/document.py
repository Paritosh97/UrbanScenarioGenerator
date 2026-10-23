"""Specification documents: the declarative first stage of the L2 pipeline.

A document is ``{"defs": {...}, "tasks": [ {name, instruction, goal, safety, timeout, after, ...} ]}``. It is DATA: it
is checked here without running any code, then applied to a scenario with ``ScenarioBuilder.apply_spec``.
"""
from __future__ import annotations

import math
from typing import Optional

from .. import geo
from . import formula as F

WALK_SPEED = 1.2


def document_from_spec(spec: dict) -> dict:
    """Readable specification document of a built scenario (tasks written with go_to / cross / apply_spec alike).

    Applying the result with ``ScenarioBuilder.apply_spec`` reproduces the same formulas (round trip, tested).
    """
    by_id = {t["id"]: t for t in spec["tasks"]}
    tasks = []
    for t in spec["tasks"]:
        raw = t.get("spec_raw") or {}
        d: dict = {"name": t["name"], "instruction": t["instruction"].get("en", ""),
                   "goal": raw.get("goal") or t["goal"], "safety": list(raw.get("safety") or t["safety"]),
                   "timeout": {"initial": t["timeout"]["initial"], "baseline": t["timeout"]["baseline"]}}
        if t["depends_on"]:
            d["after"] = [by_id[i]["name"] for i in t["depends_on"] if i in by_id]
        if t["group"]:
            d["group"], d["mode"] = t["group"], t["mode"]
        if not t["required"]:
            d["required"] = False
        if t["start_time"]:
            d["start_time"] = t["start_time"]
        tasks.append(d)
    return {"tasks": tasks}


def check_document(doc, q, level: int = 2) -> dict:
    """Static checks of a specification against the map (no entities yet; the script creates those).

    Returns ``{"ok": bool, "errors": [...], "warnings": [...], "needs": {...}, "tasks": [...]}``.
    """
    from ..dsl.builder import ScenarioBuilder
    errors: list[str] = []
    warnings: list[str] = []
    m = q._m
    sc = ScenarioBuilder("check", q, scenario_type="custom")
    try:
        sc.apply_spec(doc, level)
    except F.SpecError as e:
        return {"ok": False, "errors": [str(e)], "warnings": [], "needs": {}, "tasks": []}
    except (TypeError, ValueError, KeyError) as e:
        return {"ok": False, "errors": [f"{type(e).__name__}: {e}"], "warnings": [], "needs": {}, "tasks": []}

    all_centres: list[tuple] = []
    all_ops: set[str] = set()
    needs_e: dict[str, str] = {}
    needs_s: set[str] = set()
    needs_ev: set[str] = set()
    summary = []
    prev_end: Optional[tuple] = None
    for t in sc.tasks:
        who = f"task '{t.name}'"
        fms = [t.spec_goal] + list(t.spec_safety)
        all_ops |= {a["op"] for fm in fms for a in F.atoms_in(fm)}
        centres = []
        for fm in fms:
            for n in sorted(F.entities_in(fm)):
                needs_e.setdefault(n, t.name)
            needs_s |= F.signals_in(fm)
            needs_ev |= F.events_in(fm)
            for z in F.zones_in(fm):
                if z["kind"] == "disc":
                    surf = m.surface_at((z["x"], z["y"]))
                    if surf in ("building", "water"):
                        errors.append(f"{who}: a zone at ({z['x']:.1f},{z['y']:.1f}) is inside a {surf}; pick a point with check_point")
        for n in F.walk(t.spec_goal):
            if n["op"] == "in_zone" and n["zone"]["kind"] in ("disc", "rect"):
                z = n["zone"]
                centres.append((z["x"], z["y"]) if z["kind"] == "disc" else (z["cx"], z["cy"]))
        all_centres += centres
        # the walking route through the goal zones, in formula order
        need = 0.0
        a: Optional[tuple] = None
        for c in centres:
            if a is not None:
                r = m.ped_graph.route(a, c)
                if r is None:
                    errors.append(f"{who}: no pedestrian route between consecutive zones ({a[0]:.0f},{a[1]:.0f}) -> ({c[0]:.0f},{c[1]:.0f}) (blocked by rail/water/gaps)")
                else:
                    need += r["length"] / WALK_SPEED
            a = c
        waits = sum(float(n["end"]) - float(n.get("start", 0)) for n in F.walk(t.spec_goal)
                    if n["op"] == "always" and n.get("end") is not None and n["arg"]["op"] == "in_zone")
        to = t.timeout
        if to.baseline < to.initial:
            errors.append(f"{who}: baseline timeout ({to.baseline:g}) must be >= initial ({to.initial:g})")
        for fm in fms:
            for n in F.walk(fm):
                if n["op"] in ("eventually", "always", "until") and n.get("end") is not None and n["end"] > to.baseline:
                    warnings.append(f"{who}: a time window ends at {n['end']:g} s but the baseline timeout is {to.baseline:g} s")
        summary.append({"name": t.name, "goal": F.describe(t.spec_goal)[:200], "rules": [x.get("label", "") for x in t.spec_safety],
                        "walking_s": round(need), "holds_s": round(waits)})
        prev_end = a
    del prev_end
    needs = {"entities": {k: f"referenced by task '{v}'" for k, v in sorted(needs_e.items())},
             "signals": sorted(needs_s), "events": sorted(needs_ev)}
    return {"ok": not errors, "errors": errors, "warnings": warnings, "needs": needs, "tasks": summary, "zones": all_centres, "ops": sorted(all_ops)}


def feedback_text(r: dict) -> str:
    """Compact text for the agent loop."""
    if not r["ok"]:
        return "REJECTED: fix the errors and submit the specification again.\n" + "\n".join(f"[ERROR] {e}" for e in r["errors"])
    lines = ["OK: specification accepted."]
    if r["warnings"]:
        lines += [f"[WARNING] {w}" for w in r["warnings"]]
    n = r["needs"]
    need = []
    if n.get("entities"):
        need.append("create these entities in the script: " + ", ".join(f"{k} ({v})" for k, v in n["entities"].items()))
    if n.get("signals"):
        need.append("define these signals with scenario.signal_cycle(): " + ", ".join(n["signals"]))
    if n.get("events"):
        need.append("these storyboard events must exist: " + ", ".join(n["events"]))
    if need:
        lines.append("Your script must now: " + "; ".join(need) + ".")
    lines.append("Next: call submit_script with a script that builds the world (user start, vehicles, walkers, signals) and then "
                 "calls scenario.apply_spec(SPEC). Do NOT add go_to/cross/follow_path tasks.")
    return "\n".join(lines)
