from usg.dsl import *

# Point-to-point ROAD navigation: the destination is on the carriageway itself.
cr = MAP.crossings()[0]
cid, road, s = cr["id"], cr["road"], cr["road_s"]
start = MAP.crossing_side(cid, "start", inset=2.0)
dest = MAP.along_road(road, s + 6.0)          # a point on the carriageway just past the crossing

scenario = ScenarioBuilder("ptp_road_stand_on_road", MAP, scenario_type="ptp_road",
                           description="Walk onto the road and stand on the marked spot.")
scenario.user(start)
scenario.go_to(dest, "Walk onto the road and stand on the marked spot", name="to_road_point",
               target_name="road_spot", tolerance=1.5, timeout=60,
               success="You reached the spot on the road.", failure="Time is up.")
