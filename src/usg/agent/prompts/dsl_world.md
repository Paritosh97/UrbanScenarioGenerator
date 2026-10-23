# World-building script reference

A script is plain Python that ends with a variable named `scenario`. `MAP` (read-only map) and `SPEC` (your accepted specification) are already defined.
Start every script with `from usg.dsl import *`. All positions are metres in one frame: x = east, y = north; angles in radians.

## MAP queries
- `MAP.crossings(control=None)` -> [{id, road, road_s, control: zebra|signals|uncontrolled, signal_id, center, length_m}]
- `MAP.roads()`, `MAP.road(road_id)` -> {id, length, width, lanes, oneway, speed_limit_mps, ...}; `MAP.bus_stops()`, `MAP.props(ptype=None)`, `MAP.paths()`
- `MAP.place(feature_id, u=0.5, v=0)`; `MAP.crossing_side(crossing_id, "start"|"end", inset=1.5)` -> Place on the sidewalk before ("start") or after ("end") a crossing
- `MAP.along_road(road_id, s, t=0)`, `MAP.sidewalk_at(road_id, "left"|"right", s)`
- `MAP.lane_center(road_id, s, "forward"|"backward")`, `MAP.drive_route(road_id, s_from, s_to, "forward", step=10)` -> lane-centre Places for vehicles
- `MAP.kerb_slots(road_id, "right"|"left", spacing=7)` -> Places for parked cars
- `MAP.walk_time(a, b)` -> a safe walking timeout in seconds
- Vehicles must be built from `MAP.drive_route(...)` / `MAP.lane_center(...)`, never from hand-typed coordinates.

## ScenarioBuilder
```
scenario = ScenarioBuilder("name", MAP, scenario_type="custom", description="one sentence")
scenario.user(start_place)                                        # optional with a specification: omitted -> the participant is placed ~18 m before the first goal zone, facing it
scenario.vehicle("Car1", start, route=[...], speed=8, model="car_white", start_when=when_time(0))
scenario.parked_vehicle("Car2", slot_place, model="car_red")      # static obstacle
scenario.walker("Ped1", start, route=[...], speed=1.3)            # NPC pedestrian
scenario.signal_cycle(crossing_id, green=15, red=20, initial="red")   # returns the signal name; needed for signals named in the spec
handles = scenario.apply_spec(SPEC)                               # creates the tasks from your specification (call it ONCE; handles are in task order)
```
Vehicle models: car_white car_red car_blue car_yellow van_red bus_blue truck_yellow.
start_when: `when_time(t)`, `when_user_within(metres)` (when the participant comes that close), `when_task_starts(handles[0])` / `when_task_done(handles[0])` (call apply_spec BEFORE creating such an entity).

## Rules
- Use ONLY ids and numbers that come from tool results. Never invent ids.
- Entity names in the script must match the names used in the specification exactly.
- Allowed imports: `from usg.dsl import *`, `import math`. No file access, no classes, no names starting with `_`.
- The script must define `scenario`. Do not call write/save methods.
