from usg.dsl import *

# DYNAMIC navigation: a moving car the user has to react to while crossing.
crossings = MAP.crossings(control="zebra") or MAP.crossings()
cr = sorted(crossings, key=lambda c: (MAP.road(c["road"])["oneway"], -MAP.road(c["road"])["lanes"], -MAP.road(c["road"])["length"]))[0]   # prefer a two-way road
cid, road, s = cr["id"], cr["road"], cr["road_s"]
length = MAP.road(road)["length"]

scenario = ScenarioBuilder("dyn_nav_approaching_car", MAP, scenario_type="dyn_nav",
                           description="Cross a road while a car approaches; avoid it.")
scenario.user(MAP.crossing_side(cid, "start", inset=2.0))
task = scenario.cross(cid, "start", "Check the traffic, then cross", name="cross_with_traffic",
                      avoid=["Car1"], timeout=60,
                      success="You crossed safely.", failure="The car hit you. Look before you cross.")
route = MAP.drive_route(road, max(0.0, s - 30.0), min(length, s + 30.0), "forward")
scenario.vehicle("Car1", route[0], route[1:], speed=8.0, model="car_white", start_when=when_task_starts(task))
