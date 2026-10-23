"""A readable table of the OpenSCENARIO storyboard: every event, who it acts on, what starts it and what it does."""
from __future__ import annotations

import xml.etree.ElementTree as ET

HEADERS = ["event", "acts on", "starts when", "does"]


def _cond(c: ET.Element) -> str:
    st = c.find(".//SimulationTimeCondition")
    if st is not None:
        return f"t >= {float(st.get('value', 0)):g} s"
    se = c.find(".//StoryboardElementStateCondition")
    if se is not None:
        return f"{se.get('storyboardElementRef')} {se.get('state', '').replace('Transition', '')}s"
    rd = c.find(".//RelativeDistanceCondition")
    if rd is not None:
        return f"{rd.get('entityRef')} within {float(rd.get('value', 0)):g} m"
    return c.get("name", "condition")


def _action(a: ET.Element) -> str:
    task = a.find(".//VRTask")
    if task is not None:
        return f"VR task {task.get('id')}: {task.get('name')} ({task.get('category')})"
    sp = a.find(".//AbsoluteTargetSpeed")
    if sp is not None:
        return f"speed {float(sp.get('value', 0)):g} m/s"
    tr = a.find(".//FollowTrajectoryAction")
    if tr is not None:
        verts = tr.findall(".//Vertex")
        return f"follow a {len(verts)}-point route ({float(verts[-1].get('time', 0)):g} s)" if verts else "follow route"
    sig = a.find(".//TrafficSignalStateAction")
    if sig is not None:
        return f"signal {sig.get('name')} -> {sig.get('state')}"
    return a.get("name", "action")


def storyboard_rows(xosc: str) -> list[list[str]]:
    root = ET.fromstring(xosc)
    rows: list[list[str]] = []
    for mg in root.iter("ManeuverGroup"):
        actors = ", ".join(e.get("entityRef", "") for e in mg.findall("./Actors/EntityRef"))
        for ev in mg.iter("Event"):
            start = []
            for grp in ev.findall("./StartTrigger/ConditionGroup"):
                start.append(" and ".join(_cond(c) for c in grp.findall("Condition")))
            rows.append([ev.get("name", ""), actors, " or ".join(start) or "immediately",
                         "; ".join(_action(a) for a in ev.findall("Action"))])
    return rows
