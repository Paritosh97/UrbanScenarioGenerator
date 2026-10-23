from usg.dsl import *

# ENVIRONMENTALLY CONSTRAINED navigation: static obstacles (parked cars) the user must not touch.
crossings = MAP.crossings(control="zebra") or MAP.crossings()
cr = sorted(crossings, key=lambda c: (MAP.road(c["road"])["oneway"], -MAP.road(c["road"])["lanes"], -MAP.road(c["road"])["length"]))[0]   # prefer a two-way road
cid, road = cr["id"], cr["road"]
centre = MAP.place(cid)
slots = sorted([p for p in MAP.kerb_slots(road, "right", 7.0) if p.dist(centre) > 8.0],
               key=lambda p: p.dist(centre))[:4]

scenario = ScenarioBuilder("env_con_parked_cars", MAP, scenario_type="env_con",
                           description="Cross the road past a row of parked cars without touching them.")
scenario.user(MAP.crossing_side(cid, "start", inset=1.5))
cars = [scenario.parked_vehicle("Car" + str(i + 1), p, VEHICLE_MODELS[i % 4]) for i, p in enumerate(slots)]
scenario.cross(cid, "start", "Cross the road without touching the parked cars", name="cross_past_parked",
               avoid=cars, timeout=60, success="You crossed safely.", failure="You bumped into a parked car.")
