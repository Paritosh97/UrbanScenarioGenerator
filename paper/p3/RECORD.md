# Scenario record (approved 27 Nov 2026): P11, P12, P13, P16

Not implemented. Nothing in the two examples has been run.

## 1. Idea
`window -> record -> {request, L0 reply, L1 reply, verifier checks}`
The generator samples only the record. Everything else is derived from it.

| problem | how the record handles it |
|---|---|
| P11 | every record field is either written in the request or fixed by a rule in section 3 (the rules go into the system prompt) |
| P12 | the request is rendered from all non-default fields, using window ids |
| P13 | one record per (window, level, request); a duplicate key is dropped |
| P16 | one check per field, comparing the built scenario with the record |

## 2. Fields
| field | values | must appear in the request |
|---|---|---|
| window | stored window id | no (it is the map in the prompt) |
| start | point (x, y) on walkable ground, facing target | yes |
| stages (1-3) | reach(object or point), cross(crossing, from side), wait_for_green(crossing, side), look(vehicle), hold(place, seconds) | yes |
| order | one / ordered / any | yes if more than one stage |
| vehicles | name, type, parked (place) or moving (roads in driving order, meeting place, speed, trigger) | yes |
| signal | crossing, green s, red s, initial state | yes if present |
| rules (0-3) | obey_signal, collision_free, keep_clear(d), corridor(width), stay_on(surface) | yes |
| time limits | seconds per stage | only if not the default |

## 3. Fixed defaults (stated once in the system prompt)
| item | default |
|---|---|
| goal radius | 1.5 m for objects and points, 2 m for a crossing side (inset 1 m) |
| collision | closer than 0.3 m to a vehicle body |
| look | within 45 degrees, within 12 s |
| signal cycle | green 15 s, red 20 s, starts red |
| time limit | 60 s per stage, baseline 90 s |
| facing at start | toward the first target |
| moving car start | computed by the simulator from speed and meeting place; the reply gives no distance |

## 4. Verifier: one check per field (P16)
| field | check |
|---|---|
| start | user start within 1 m of the record point |
| stages | same number and kinds; each zone, entity or signal matches the record id or point (1 m) |
| order | dependencies match one / ordered / any |
| vehicles | same count and type; parked: position within 1 m; moving: road sequence, speed, trigger |
| encounter | simulated car and reference walker are within N m of each other at the meeting place (N to be decided) |
| signal | crossing id, green, red, initial state |
| rules | same rule set and parameters; no extra rule |
| time limits | equal |
The same record checks L0 and L1 replies, since both end in the same task specification.

## 5. Example A: look, then cross, with an approaching car (`paper/p1/v2/crossing.txt`)
```json
{"window": "crossing",
 "start": [-1.9, -8.8],
 "stages": [{"kind": "look", "entity": "Car1"},
            {"kind": "cross", "crossing": "crossing_1", "from": "start"}],
 "order": "ordered",
 "vehicles": [{"name": "Car1", "type": "car", "roads": ["road_6", "road_2"], "meet": "crossing_1", "speed": 5, "trigger": "scenario_start"}],
 "rules": [{"kind": "keep_clear", "entity": "Car1", "d": 1.0}]}
```
Request:
> Start at (-1.9, -8.8). A car (Car1) comes from outside the map along road_6 and turns onto road_2 toward crossing_1, driving 5 m/s from the start of the scenario.
> First look at Car1, then cross crossing_1 from its start side. Stay at least 1 m away from Car1.

L0:
```python
from usg.dsl import *
scenario = ScenarioBuilder("scenario", MAP, scenario_type="custom")
start = Place(-1.9, -8.8)
scenario.user(start.facing(MAP.place("crossing_1")))
scenario.approaching_vehicle("Car1", ["road_6", "road_2"], meet="crossing_1", speed=5, model="car_white")
t1 = scenario.look_at("Car1", "Look at the car.", name="look_car")
t2 = scenario.cross("crossing_1", "start", "Cross and keep clear of the car.", name="cross", tolerance=2.0,
                    stay_on_crossing=False, keep_clear={"Car1": 1.0})
scenario.sequence([t1, t2])
```
L1:
```json
{"tasks": [
 {"name": "look_car", "instruction": "Look at the car.",
  "goal": {"op": "call", "name": "look", "args": {"entity": "Car1", "angle": 45, "seconds": 12}}},
 {"name": "cross", "instruction": "Cross and keep clear of the car.", "after": ["look_car"],
  "goal": {"op": "call", "name": "cross", "args": {"far_zone": {"kind": "crossing_side", "id": "crossing_1", "side": "end", "inset": 1.0, "r": 2.0}}},
  "safety": [{"op": "call", "name": "collision_free", "args": {"entity": "Car1", "r": 1.0}}]}]}
```
```python
from usg.dsl import *
scenario = ScenarioBuilder("scenario", MAP, scenario_type="custom")
scenario.user(Place(-1.9, -8.8).facing(MAP.place("crossing_1")))
scenario.approaching_vehicle("Car1", ["road_6", "road_2"], meet="crossing_1", speed=5, model="car_white")
handles = scenario.apply_spec(SPEC)
```
Distance example (assumed: look takes 3 s, walking 1.2 m/s): start to crossing centre 4 m, so the car needs 5 x (3 + 3.3) = 31.5 m.
About 22.5 m of that is inside the window, so it starts about 9 m outside.

**Outdated:** speed predicates were removed from the language later on 27 Nov, so the speed rule in example B no longer exists.

## 6. Example B: hold, then reach, with a speed limit (`paper/p1/v2/junction.txt`)
```json
{"window": "junction",
 "start": [10.8, -14.0],
 "stages": [{"kind": "hold", "place": "bench_9", "seconds": 5},
            {"kind": "reach", "place": "bench_7"}],
 "order": "ordered",
 "vehicles": [],
 "rules": [{"kind": "pace", "max": 1.8}]}
```
Request:
> Start at (10.8, -14). Go to bench_9 and stay there for 5 seconds, then walk to bench_7. Never walk faster than 1.8 m/s.

L0:
```python
from usg.dsl import *
scenario = ScenarioBuilder("scenario", MAP, scenario_type="custom")
scenario.user(Place(10.8, -14.0).facing(MAP.place("bench_9")))
t1 = scenario.hold(MAP.place("bench_9"), 5, "Wait at the bench.", name="wait_bench", radius=1.5, pace=(0, 1.8))
t2 = scenario.go_to(MAP.place("bench_7"), "Walk to the next bench.", name="to_bench", tolerance=1.5, timeout=60, pace=(0, 1.8))
scenario.sequence([t1, t2])
```
L1:
```json
{"tasks": [
 {"name": "wait_bench", "instruction": "Wait at the bench.",
  "goal": {"op": "call", "name": "hold", "args": {"zone": {"kind": "feature", "id": "bench_9", "r": 1.5}, "seconds": 5}},
  "safety": [{"op": "call", "name": "pace", "args": {"vmin": 0, "vmax": 1.8, "seconds": 60}}]},
 {"name": "to_bench", "instruction": "Walk to the next bench.", "after": ["wait_bench"],
  "goal": {"op": "call", "name": "reach", "args": {"zone": {"kind": "feature", "id": "bench_7", "r": 1.5}}},
  "safety": [{"op": "call", "name": "pace", "args": {"vmin": 0, "vmax": 1.8, "seconds": 60}}]}]}
```
World script: `scenario.user(...)` and `scenario.apply_spec(SPEC)` as in A.

## 7. Needed before these examples can run
1. `approaching_vehicle` helper: does not exist. It computes the start outside the window and drives to the meeting place.
2. Window ids (road_2, bench_9) must resolve in the simulator (P32).
3. L0 time-limit defaults differ between helpers; align them with section 3.

## 8. Decisions (27 Nov 2026)
* Record, fields and fixed defaults: approved.
* A moving car starts at scenario start.
* Letting the car pass is a valid way to solve the task. The verifier requires the car to reach the meeting place about when a walker who does not wait would; the allowed gap N is still to be chosen.
