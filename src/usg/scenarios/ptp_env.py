from usg.dsl import *

# Point-to-point ENVIRONMENT navigation: reach a landmark using walkable areas only (no road use).
candidates = MAP.bus_stops() + MAP.props("bench") + MAP.props("waste_basket") + MAP.props("street_lamp") + MAP.props()
landmarks = [p for p in candidates if p["road"] and MAP.surface(MAP.place(p["id"])) in ("sidewalk", "path", "ground")]
stop = landmarks[0]                                   # a bus stop if the map has one, else another landmark on walkable ground
dest = MAP.place(stop["id"])
road = stop["road"]
side = MAP.side_of_road(dest)
start = MAP.sidewalk_at(road, side, max(6.0, MAP.road_s_of(dest) - 40.0))     # ~40 m back along the same sidewalk

scenario = ScenarioBuilder("ptp_env_landmark", MAP, scenario_type="ptp_env",
                           description="Walk along the sidewalk to the marked landmark.")
scenario.user(start.facing(dest))
scenario.go_to(dest, "Walk along the sidewalk to the bus stop", name="to_landmark",
               target_name="landmark", tolerance=2.0, timeout=MAP.walk_time(start, dest),
               success="You reached the bus stop.", failure="Time is up. Head for the bus stop.")
