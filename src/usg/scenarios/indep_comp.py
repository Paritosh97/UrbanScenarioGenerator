from usg.dsl import *

# INDEPENDENT composite: several goals that can be completed in ANY order.
by_road = {}
for p in MAP.props():
    if p["road"]:
        by_road.setdefault(p["road"], []).append(p)
road, items = max(by_road.items(), key=lambda kv: len(kv[1]))     # the street with the most landmarks
a_prop, b_prop = items[0], items[-1]                                # two landmarks on the same street
a_pl, b_pl = MAP.place(a_prop["id"]), MAP.place(b_prop["id"])
mid = a_pl.shifted(0.0, 0.0)
start = MAP.sidewalk_at(road, MAP.side_of_road(a_pl), (MAP.road_s_of(a_pl) + MAP.road_s_of(b_pl)) / 2)   # between them

scenario = ScenarioBuilder("indep_comp_two_landmarks", MAP, scenario_type="indep_comp",
                           description="Visit both landmarks, in any order.")
scenario.user(start)
a = scenario.go_to(a_pl, "Walk to the first landmark (a " + a_prop["type"].replace("_", " ") + ")", name="to_first",
                   tolerance=2.0, timeout=MAP.walk_time(start, a_pl))
b = scenario.go_to(b_pl, "Walk to the second landmark (a " + b_prop["type"].replace("_", " ") + ")", name="to_second",
                   tolerance=2.0, timeout=MAP.walk_time(start, b_pl))
scenario.parallel([a, b], "any_order")
