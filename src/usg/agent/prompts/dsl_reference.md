# Scenario DSL reference

A scenario script is plain Python that ends with a variable named `scenario`.
`MAP` is already defined (read-only map). Start every script with `from usg.dsl import *`.
All positions are metres in one frame: x = east, y = north. Angles are radians (0 = east, counter-clockwise).

## Places
- `Place` has x, y, h (heading). `p.dist(q)`, `p.facing(q)` (same spot, turned to look at q), `p.shifted(ahead=, left=)`.
- `at(x, y, heading=0)` makes a Place at raw coordinates.

## MAP queries (return plain dicts/lists or Place)
- `MAP.crossings(control=None)` -> [{id, road, road_s, control: zebra|signals|uncontrolled, signal_id, center, length_m}]
- `MAP.roads()`, `MAP.road(road_id)` -> {id, length, width, lanes, oneway, speed_limit_mps, sidewalk_left, sidewalk_right, trim}
- `MAP.junctions()`, `MAP.signals()`, `MAP.bus_stops()`, `MAP.props(ptype=None)` (waste_basket, bench, tree, street_lamp, bollard, bus_stop), `MAP.paths()`, `MAP.buildings()`
- `MAP.place(feature_id, u=0.5, v=0)` -> Place on a feature (crossing: u 0 = right kerb ... 1 = left kerb)
- `MAP.crossing_side(crossing_id, "start"|"end", inset=1.5)` -> Place on the sidewalk just before ("start" = right-hand kerb) or after ("end" = left-hand kerb) the crossing, facing across the road
- `MAP.along_road(road_id, s, t=0)` -> Place on the road at arc length s (t = metres left of centre-line)
- `MAP.sidewalk_at(road_id, "left"|"right", s)` -> Place on the sidewalk beside the road at arc length s
- `MAP.lane_center(road_id, s, "forward"|"backward")`, `MAP.drive_route(road_id, s_from, s_to, "forward", step=10)` -> list of lane-centre Places for vehicles
- `MAP.kerb_slots(road_id, "right"|"left", spacing=7)` -> list of Places for parked cars
- `MAP.side_of_road(place)` -> "left"|"right"; `MAP.route(a, b)` -> list of Places along sidewalks/crossings; `MAP.route_info(a, b)`; `MAP.surface(place)`
- `MAP.walk_time(a, b)` -> a safe timeout in seconds for walking a -> b (use it for `timeout=` so tasks are never too short); `MAP.road_s_of(place)` -> arc length of the place along its nearest road
- Vehicles must be built from `MAP.drive_route(...)` / `MAP.lane_center(...)`, never from hand-typed coordinates. Prefer crossings on wide two-way roads (check `MAP.road(id)`: `oneway`, `lanes`, `width`).

## ScenarioBuilder
```
scenario = ScenarioBuilder("name", MAP, scenario_type="<one of 7 ids>", description="one sentence")
scenario.user(start_place)                       # REQUIRED, exactly once
scenario.vehicle("Car1", start, route=[...], speed=8, model="car_white", start_when=when_task_starts(task))
scenario.parked_vehicle("Car2", slot_place, model="car_red")        # static obstacle
scenario.walker("Ped1", start, route=[...], speed=1.3)               # NPC pedestrian
scenario.signal_cycle(crossing_id, green=15, red=20, initial="red")  # needed for signal crossings
```
Vehicle models: car_white car_red car_blue car_yellow van_red bus_blue truck_yellow.
start_when: `when_time(t)`, `when_task_starts(task)`, `when_task_done(task)`, `when_user_within(metres)`.

### Tasks (each returns a handle)
```
go_to(place, instruction, name=, tolerance=1.5, timeout=60, avoid=[entity names], on_surface=None, after=[], success=, failure=)
cross(crossing_id, from_side="start", instruction, name=, timeout=60, avoid=[...], obey_signal=True, after=[], success=, failure=)
follow_path([places...], instruction, name=, corridor=2.0, timeout=90, avoid=[...], after=[], success=, failure=)
scenario.sequence([t1, t2, t3])   # must be done in this order
scenario.parallel([t1, t2])       # all active at once, any order
```
- `instruction` is the text shown on the HUD (max 160 chars). `success`/`failure` are feedback messages.
- `timeout` is the allowed time in seconds; it must exceed route_length / 1.2 m/s with margin.
- `avoid=["Car1"]` makes touching those entities a failure. Entities may be created after the task.
- Obeying a signal needs `scenario.signal_cycle(crossing_id, ...)` for that crossing.

## The 7 scenario types (scenario_type=)
ptp_env: reach a target on sidewalks/paths. ptp_road: reach a target ON the road surface. cpath: stay inside a path corridor (follow_path).
env_con: static obstacles to avoid (>=2 parked_vehicle + avoid=). dyn_nav: a moving vehicle/walker to avoid (route + avoid=).
dep_comp: ordered tasks (sequence). indep_comp: any-order tasks (parallel).

## Rules
- Use ONLY ids and numbers that come from tool results. Never invent ids.
- Allowed imports: `from usg.dsl import *`, `import math`. No file access, no `open`, no classes, no names starting with `_`.
- The script must define `scenario`. Do not call write/save methods; the app does that.
