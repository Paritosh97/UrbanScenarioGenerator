from usg.dsl import *

# DEPENDENT composite: tasks that must be completed in order (walk to crossing -> cross -> walk on).
crossings = MAP.crossings(control="zebra") or MAP.crossings()
cr = sorted(crossings, key=lambda c: -MAP.road(c["road"])["length"])[0]
cid, road, s = cr["id"], cr["road"], cr["road_s"]
info = MAP.road(road)
start = MAP.sidewalk_at(road, "right", max(info["trim"][0] + 2.0, s - 20.0))
final = MAP.sidewalk_at(road, "left", min(info["length"] - 8.0, s + 20.0))
kerb = MAP.crossing_side(cid, "start", inset=1.5)

scenario = ScenarioBuilder("dep_comp_walk_cross_walk", MAP, scenario_type="dep_comp",
                           description="Walk to the crossing, cross, then continue to the marked spot.")
scenario.user(start.facing(MAP.crossing_side(cid, "start")))
t1 = scenario.go_to(kerb, "Walk to the crossing", name="to_crossing", tolerance=2.0, timeout=MAP.walk_time(start, kerb))
t2 = scenario.cross(cid, "start", "Cross the road", name="cross", timeout=45)
t3 = scenario.go_to(final, "Continue to the marked spot", name="walk_on", tolerance=2.0,
                    timeout=MAP.walk_time(MAP.crossing_side(cid, "end", inset=1.5), final))
scenario.sequence([t1, t2, t3], "walk_cross_walk")
