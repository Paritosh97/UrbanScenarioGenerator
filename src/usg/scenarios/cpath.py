from usg.dsl import *

# CONSTRAINED PATH navigation: reach the goal while staying inside a corridor around a given path.
cr = MAP.crossings()[0]
cid = cr["id"]
a = MAP.crossing_side(cid, "start", inset=2.0)
mid = MAP.place(cid, 0.5, 0.0)
b = MAP.crossing_side(cid, "end", inset=2.0)

scenario = ScenarioBuilder("cpath_crossing_corridor", MAP, scenario_type="cpath",
                           description="Cross the road while staying on the marked path.")
scenario.user(a)
scenario.follow_path([a, mid, b], "Cross along the marked path and stay inside the corridor",
                     name="follow_crossing_path", corridor=1.8, timeout=60,
                     success="You stayed on the path.", failure="You left the marked path.")
