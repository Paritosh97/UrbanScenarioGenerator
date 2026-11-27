```python
from usg.dsl import *
scenario = ScenarioBuilder("scenario", MAP, scenario_type="custom")
scenario.user(Place(-1.9, 4.1).facing(MAP.place("crossing_1")))
scenario.signal_cycle("crossing_1", green=10, red=25, initial="red")
scenario.approaching_vehicle("Car1", ["road_4"], meet="crossing_1", speed=7, model="car_white")
t1 = scenario.look_at("Car1", "Look at the vehicle.", name="t1_look")
t2 = scenario.wait_for_green("crossing_1", "end", "Wait for green.", name="t2_wait_for_green")
t3 = scenario.cross("crossing_1", "end", "Cross the street.", tolerance=2.0, obey_signal=True, name="t3_cross", keep_clear={"Car1": 0.3})
scenario.sequence([t1, t2, t3])
```
