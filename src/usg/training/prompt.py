"""The prompt of the window pipeline (L1): one system prompt, and a user prompt made of the map text and the request."""
from __future__ import annotations

from . import records as R

_EXAMPLE = ('{"start":[2,-3.5],"tasks":[{"name":"t1_reach","instruction":"Walk to the bench.",'
            '"goal":{"op":"call","name":"reach","args":{"zone":{"kind":"feature","id":"bench_0","r":1.5}}},'
            '"timeout":{"initial":60,"baseline":90}}]}')

SYSTEM = f"""You turn a request into a guided pedestrian task on a 30 x 30 m map of a real street.
Reply with ONE ```json block holding the scenario document, and nothing else.

DOCUMENT: {{"start":[x,y],
 "signals":[{{"crossing":C,"green":s,"red":s,"initial":"red"|"green"}}],
 "vehicles":[PARKED or MOVING],
 "tasks":[{{"name":"t1_kind","instruction":"short sentence","goal":F,"safety":[F,...],"timeout":{{"initial":{R.LIMIT},"baseline":{R.BASELINE}}},
   "after":["earlier task"] or "mode":"parallel"}}]}}
"signals" and "vehicles" only if the request has them.
PARKED: {{"name":N,"type":M,"at":[x,y]}}
MOVING: {{"name":N,"type":M,"roads":[road ids in driving order],"meet":crossing id or [x,y],"speed":m/s}}
M: car_white car_red car_blue car_yellow (cars), van_red, bus_blue, truck_yellow.
One task per requested step, in the order of the request. Order: tasks one after another use "after" with the task before; tasks in free order use "mode":"parallel".

ZONES: {{"kind":"feature","id":ID,"r":}} | {{"kind":"disc","x":,"y":,"r":}} | {{"kind":"crossing","id":C}} (the crossing area) |
{{"kind":"crossing_side","id":C,"side":"start"|"end","inset":{R.INSET},"r":}} (a crossing is listed kerb to kerb: first point "start", second "end")
SIGNAL NAME of a crossing: the signal id listed for it, otherwise <crossing id>_ped.

FORMULAS are JSON objects. Time is counted in seconds from the start of the task.
Predicates: {{"op":"in_zone","zone":Z}}, {{"op":"on_surface","surface":"sidewalk"|"road"|...}}, {{"op":"near_path","path":[[x,y],..],"tol":}},
{{"op":"dist_le"|"dist_ge","entity":N,"d":}}, {{"op":"look_at","entity":N,"angle":}}, {{"op":"signal_is","signal":S,"state":"green"|"red"}}
Logic: {{"op":"not","arg":F}}, {{"op":"and"|"or","args":[F,..]}}, {{"op":"implies","a":F,"b":F}}
Time: {{"op":"eventually"|"always","arg":F,"start":0,"end":null}}, {{"op":"until","left":F,"right":F,"start":0,"end":null}}
Definitions {{"op":"call","name":N,"args":{{...}}}}: reach(zone), reach_within(zone,seconds), hold(zone,seconds), cross(far_zone),
wait_for_green(zone,signal), look(entity,angle,seconds), collision_free(entity,r), stay_on(surface), stay_near_path(path,tol), obey_signal(zone,signal)

DEFAULTS, used whenever the request does not say otherwise:
- radius {R.R_PLACE} m for an object or point; {R.R_SIDE} m for a crossing side (inset {R.INSET} m)
- a collision means closer than {R.COLLISION_D} m to a vehicle
- looking: within {R.LOOK_ANGLE} degrees; a look task has {R.LOOK_S} s
- "near" a place that must be avoided: within {R.AVOID_R} m
- signal cycle: green {R.GREEN} s, red {R.RED} s, starts {R.INITIAL}
- time limit {R.LIMIT} s per task (baseline {R.BASELINE} s)
- a moving vehicle starts with the scenario; the simulator chooses its start point
- rules about vehicles, places to avoid, the sidewalk or a line hold in every task; signal rules and "look before stepping on the road" belong to the crossing task
- "do not visit a later place early" is a rule of each earlier task

Example reply (the ids are placeholders; use those of the request):
```json
{_EXAMPLE}
```"""


def system_prompt() -> str:
    return SYSTEM


def user_prompt(map_text: str, request: str) -> str:
    return f"{map_text}\n\n# REQUEST\n{request}"
