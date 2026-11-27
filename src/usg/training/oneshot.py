"""The one-shot condition: one compact prompt, one reply, checked once by the same gates as the agent (no tools, no repair).

The identical prompt is used for the base, the fine-tuned and the RL model, in data generation, reward and evaluation.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .. import geo, grounding
from ..tools import ToolServer

# ------------------------------------------------------------------ compact references
_DSL_COMMON = """MAP queries: MAP.crossings(control=None), MAP.road(id) -> {length,lanes,oneway,trim}, MAP.bus_stops(), MAP.props(type), MAP.place(feature_id),
MAP.crossing_side(crossing_id,"start"|"end",inset=1.5), MAP.along_road(road_id,s,t=0), MAP.sidewalk_at(road_id,"left"|"right",s), MAP.side_of_road(place),
MAP.road_s_of(place), MAP.walk_time(a,b), MAP.drive_route(road_id,s_from,s_to,"forward"), MAP.kerb_slots(road_id,"right"|"left",spacing).
Entities: scenario.vehicle("Car1", route[0], route[1:], speed=8, model="car_white", start_when=when_task_starts(handle))
(models car_white car_red car_blue car_yellow van_red bus_blue truck_yellow; start_when also when_time(t), when_user_within(m)),
scenario.parked_vehicle("Car1", place, model="car_red"), scenario.signal_cycle(crossing_id, green=15, red=20, initial="red").
Start with `from usg.dsl import *`; only `import math` besides; define `scenario`. Use only ids given in the request context."""

SYSTEM_L0 = """You write one Python script that builds a guided pedestrian task on a real street map. Reply with ONE ```python block and nothing else.
`scenario = ScenarioBuilder("name", MAP, scenario_type=T, description="...")` with T one of ptp_env, ptp_road, cpath, env_con, dyn_nav,
dep_comp, indep_comp, custom. Then `scenario.user(place)` exactly once, then tasks (each returns a handle):
scenario.go_to(place, instruction, name=, tolerance=2.0, timeout=, avoid=[names])
scenario.cross(crossing_id, "start", instruction, name=, timeout=60, avoid=[names], obey_signal=True)
scenario.follow_path([places], instruction, name=, corridor=2.0, timeout=90)
scenario.wait_for_green(crossing_id, "start", instruction, name=, timeout=60)
scenario.approaching_vehicle(name, [road ids in driving order], meet=crossing_id, speed=5, model="car_white")
scenario.look_at(entity_name, instruction, name=, angle=45, seconds=12)
scenario.hold(place, seconds, instruction, name=, radius=1.5)
scenario.keep_near(task, [[x, y], ...], metres)
Safety options of every task: avoid=[names], keep_clear={name: metres}, stay_on="sidewalk"
scenario.sequence([t1,t2,...]) (in order) ; scenario.parallel([t1,t2]) (any order)
""" + _DSL_COMMON

_SPEC = """Reply with exactly TWO blocks and nothing else: first a ```json block with the task specification, then a ```python block with the world script.

SPECIFICATION: {"tasks":[{"name":"short_snake_name","instruction":"short sentence","goal":F,"safety":[F,...],"timeout":{"initial":60,"baseline":90},
"after":["earlier_task"],"mode":"parallel"}]%DEFS_KEY%}  (every task needs "name" and "goal"; every goal and safety item is a JSON formula object F, never text; "after" = ordered tasks; "mode":"parallel" on every task = any order)
Zones: {"kind":"crossing","id":C} | {"kind":"crossing_side","id":C,"side":"start"|"end","r":2} | {"kind":"feature","id":ID,"r":3} | {"kind":"disc","x":,"y":,"r":}
Library formulas F = {"op":"call","name":N,"args":{...}}: reach(zone), cross(far_zone), hold(zone,seconds), wait_for_green(zone,signal),
look(entity,angle,seconds), keep_clear(entity,d,seconds), collision_free(entity,r) with r 0.3, stay_on(surface),
stay_near_path(path [[x,y],..],tol), obey_signal(zone,signal)
Combinators: {"op":"then","args":[F,F]} (stages in order), {"op":"and","args":[..]}, {"op":"eventually"|"always","arg":F,"start":0,"end":null}
%DEFS%
WORLD SCRIPT: `scenario = ScenarioBuilder("name", MAP, scenario_type="custom")`, create every vehicle and signal the specification names,
then `handles = scenario.apply_spec(SPEC)` exactly once (create entities that use handles[0] after it). Do not create tasks in the script.
scenario.user(place) is optional.
"""

_DEFS = """You may add your own definitions: "defs":{"my_def":{"params":["z"],"body":F with {"param":"z"} placeholders}} and call them by name.
"""


def system_prompt(level: int) -> str:
    head = "You turn a request into a guided pedestrian task on a real street map.\n"
    if level == 0:
        return SYSTEM_L0 + EXAMPLE_L0
    spec = _SPEC.replace("%DEFS%", _DEFS if level >= 2 else "Use only the library formulas (no own definitions).")
    return head + spec.replace("%DEFS_KEY%", ',"defs":{...}' if level >= 2 else "") + _DSL_COMMON + EXAMPLE_SPEC


EXAMPLE_L0 = """
Example reply (the ids are placeholders; use those of the request):
```python
from usg.dsl import *
scenario = ScenarioBuilder("example", MAP, scenario_type="ptp_env")
dest = MAP.place("bench_0")
start = MAP.sidewalk_at("road_0", MAP.side_of_road(dest), max(6.0, MAP.road_s_of(dest) - 30.0))
scenario.user(start.facing(dest))
scenario.go_to(dest, "Walk to the bench.", name="to_bench", tolerance=2.0, timeout=MAP.walk_time(start, dest))
```"""

EXAMPLE_SPEC = """
Example reply (the ids are placeholders; use those of the request):
```json
{"tasks":[{"name":"to_bench","instruction":"Walk to the bench.","goal":{"op":"call","name":"reach","args":{"zone":{"kind":"feature","id":"bench_0","r":3}}},"timeout":{"initial":60,"baseline":90}}]}
```
```python
from usg.dsl import *
scenario = ScenarioBuilder("scenario", MAP, scenario_type="custom")
handles = scenario.apply_spec(SPEC)
```"""


# ------------------------------------------------------------------ map context
def crossing_table(t: ToolServer, per_kind: int = 3) -> list[dict]:
    """Candidate crossings given to the model: on streets of 40 m or more, nearest to the map centre first, a few of every control kind."""
    q = t.q
    length = {r["id"]: r.get("length", 0.0) for r in q.roads()}
    good = sorted((c for c in q.crossings() if length.get(c["road"], 0.0) >= 40.0), key=lambda c: geo.dist(tuple(c["center"]), (0.0, 0.0)))
    out: list[dict] = []
    for kind in ("signals", "zebra", "uncontrolled"):
        out += [c for c in good if c["control"] == kind][:per_kind]
    rows = []
    for c in out:
        r = q.road(c["road"])
        row = {"id": c["id"], "control": c["control"], "road": c["road"], "road_s": round(c["road_s"], 1), "road_length": round(r["length"]),
               "oneway": bool(r["oneway"]), "center": [round(v) for v in c["center"]],
               "start_side": [round(v, 1) for v in c["start_side"]], "end_side": [round(v, 1) for v in c["end_side"]]}
        if c["control"] == "signals":
            row["signal"] = c.get("signal_id") or f"{c['id']}_ped"
        rows.append(row)
    return rows


def user_prompt(t: ToolServer, request: str) -> str:
    table = "\n".join(json.dumps(r, separators=(",", ":")) for r in crossing_table(t))
    return (f"Request: {request}\n\n{grounding.inventory_text(t.q)}\n{grounding.requested_ids_text(request, t.q)}\n"
            f"Crossings you may use:\n{table}")


def messages(t: ToolServer, request: str, level: int) -> list[dict]:
    return [{"role": "system", "content": system_prompt(level)}, {"role": "user", "content": user_prompt(t, request)}]


# ------------------------------------------------------------------ reply -> gates
# Added by the harness at levels 1 and 2 when a reply has no python block (same rule for every model). A reply that
# starts a python block is judged on its own script.
DEFAULT_SCRIPT = """from usg.dsl import *
scenario = ScenarioBuilder("scenario", MAP, scenario_type="custom")
handles = scenario.apply_spec(SPEC)"""

_PY = re.compile(r"```(?:python)?[ \t]*\n(.*?)```", re.S)
_JS = re.compile(r"```json[ \t]*\n(.*?)```", re.S)


def parse_reply(reply: str, level: int) -> tuple[Optional[dict], str]:
    """(specification or None, script or '')."""
    spec, rest = None, reply
    if level >= 1:
        m = _JS.search(reply)
        if m:
            try:
                spec = json.loads(m.group(1))
            except ValueError:
                spec = None
            rest = reply[m.end():]
    m = _PY.search(rest)
    return spec if isinstance(spec, dict) else None, (m.group(1).strip() if m else "")


def format_reply(spec: Optional[dict], code: str) -> str:
    head = f"```json\n{json.dumps(spec, separators=(',', ':'))}\n```\n" if spec is not None else ""
    return head + f"```python\n{code.strip()}\n```"


def check(t: ToolServer, request: str, level: int, reply: str) -> dict:
    """Run one reply through the gates on a loaded map. ``t`` is reset, so it can be reused for many replies on the same map."""
    t.prompt, t.level = request, level
    t.plan = t.result = t.spec = None
    t.last_spec = t.last_code = None
    t.last_feedback = ""
    t.attempts = t.spec_attempts = 0
    spec, code = parse_reply(reply, level)
    default = level >= 1 and spec is not None and "```python" not in reply
    if default:
        code = DEFAULT_SCRIPT
    out = {"parsed": bool(code) and (level == 0 or spec is not None), "spec_ok": False, "accepted": False, "feedback": "",
           "default_script": default}
    if level >= 1:
        if spec is None:
            out["feedback"] = "no JSON specification"
            return out
        r = t.call("submit_spec", spec)
        out["spec_ok"] = bool(r.get("accepted"))
        if not out["spec_ok"]:
            out["feedback"] = str(r.get("feedback") or r.get("error"))[:600]
            return out
    if not code:
        out["feedback"] = "no script"
        return out
    r = t.call("submit_script", {"code": code})
    out["accepted"] = bool(r.get("accepted")) and t.result is not None
    if not out["accepted"]:
        out["feedback"] = str(r.get("feedback") or r.get("error"))[:600]
    return out
