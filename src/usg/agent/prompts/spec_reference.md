# Task specification language

You describe what the participant must do as DATA (JSON), not code. A specification is
`{"tasks": [ ... ]}` (and, at level 2 only, `"defs": {...}` with your own definitions).

## A task
```
{"name": "wait_then_cross",                      # unique, letters/digits/underscore
 "instruction": "Wait for green, then cross.",   # HUD text, short imperative sentence
 "goal": <formula>,                               # what must become true: the task SUCCEEDS when it is satisfied
 "safety": [<formula>, ...],                      # rules that must never be broken: the task FAILS when one is
 "timeout": {"initial": 60, "baseline": 90},      # seconds: a hint at `initial`, failure at `baseline`
 "after": ["other_task"]}                         # optional: run only after these tasks finished (in order)
```
Time bounds inside formulas are seconds from the START OF THE TASK.

## Zones (where) and what to put in them
- `{"kind":"disc","x":..,"y":..,"r":..}` a circle in metres (x east, y north)
- `{"kind":"crossing","id":"crossing_1"}` the crossing's rectangle
- `{"kind":"crossing_side","id":"crossing_1","side":"start"|"end","r":2}` the kerb just before ("start") or after ("end") the crossing
- `{"kind":"feature","id":"bus_stop_1","r":3}` any map feature id
- `{"kind":"entity","name":"Walker1","r":2}` around a moving entity

## Library definitions (use with `{"op":"call","name":..., "args":{...}}`)
| name | args | meaning |
|---|---|---|
| reach | zone | get inside a zone at some time |
| reach_within | zone, seconds | get inside a zone within `seconds` |
| cross | far_zone | get to the far side of a crossing |
| hold | zone, seconds | stay in a zone for `seconds` |
| wait_for_green | zone, signal | stay in a zone until the signal turns green |
| look | entity, angle, seconds | look at an entity (within `angle` degrees) within `seconds` |
| look_point | point[x,y], angle, seconds | look at a point |
| follow | entity, d, seconds | stay within d metres of an entity for `seconds` |
| keep_clear | entity, d, seconds | stay at least d metres from an entity for `seconds` |
| pace | vmin, vmax, seconds | walk between vmin and vmax m/s for `seconds` |
| collision_free | entity, r | never get closer than r metres to an entity (use r = 0.3) |
| stay_on | surface | never be off a surface class for more than 1 s (walkable, pedestrian_infra, crosswalk, road, sidewalk, path, ground) |
| stay_near_path | path[[x,y],..], tol | never be farther than tol metres from a path for more than 1 s |
| obey_signal | zone, signal | only step into the zone while the signal is green |
| no_event | name | this storyboard event must never start |

## Core operators (when no definition fits)
Atoms: `in_zone{zone}`, `on_surface{surface}`, `near_path{path,tol}`, `dist_le{entity,d}`, `dist_ge{entity,d}`,
`look_at{entity|point,angle}`, `speed_le{v}`, `speed_ge{v}`, `signal_is{signal,state:"green"|"red"}`, `event{name}`, `true`.
Combinators: `not{arg}`, `and{args}`, `or{args}`, `implies{a,b}`, `eventually{arg,start,end}` (some time in the window),
`always{arg,start,end}` (all the time in the window), `until{left,right}`, `then{args}` (stages in order), `prev{arg}`.
`end: null` means "until the task ends". Everything is checked and measured with numeric margins (metres, degrees, m/s).

## Examples
Wait for the pedestrian light, then cross, and never step onto the crossing on red:
```
{"tasks":[{"name":"cross_safely","instruction":"Wait for green, then cross.",
 "goal":{"op":"then","args":[
   {"op":"call","name":"wait_for_green","args":{"zone":{"kind":"crossing_side","id":"crossing_1","side":"start","r":3},"signal":"signal_1"}},
   {"op":"call","name":"cross","args":{"far_zone":{"kind":"crossing_side","id":"crossing_1","side":"end","r":2}}}]},
 "safety":[{"op":"call","name":"obey_signal","args":{"zone":{"kind":"crossing","id":"crossing_1"},"signal":"signal_1"}}],
 "timeout":{"initial":70,"baseline":110}}]}
```
Look at an approaching car within 10 s, then reach a bus stop while keeping clear of the car:
```
{"tasks":[{"name":"check_traffic","instruction":"Look at the approaching car.",
   "goal":{"op":"call","name":"look","args":{"entity":"Car1","angle":35,"seconds":10}},"timeout":{"initial":15,"baseline":20}},
  {"name":"to_stop","instruction":"Walk to the bus stop.","after":["check_traffic"],
   "goal":{"op":"call","name":"reach","args":{"zone":{"kind":"feature","id":"prop_3","r":3}}},
   "safety":[{"op":"call","name":"collision_free","args":{"entity":"Car1","r":0.3}}],"timeout":{"initial":60,"baseline":90}}]}
```
Your own definition (level 2): `"defs":{"safe_cross":{"params":["c","sig"],"body":{"op":"and","args":[
{"op":"call","name":"cross","args":{"far_zone":{"param":"c"}}},{"op":"call","name":"obey_signal","args":{"zone":{"param":"c"},"signal":{"param":"sig"}}}]}}}`
then `{"op":"call","name":"safe_cross","args":{"c":{...zone...},"sig":"signal_1"}}`. Definitions may call library definitions
and earlier ones, never themselves.

## Rules
- Use ONLY ids, signal names and numbers that come from tool results or the reference below. Never invent ids.
- Every entity named in a formula (Car1, Walker1, ...) must be created by your script; every signal needs `signal_cycle`.
- Give the participant enough time: timeouts must exceed the walking time (1.2 m/s) plus any waiting.
