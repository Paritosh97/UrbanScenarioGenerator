```json
{"tasks":[{"name":"t1_look","instruction":"Look at the vehicle.","goal":{"op":"call","name":"look","args":{"entity":"Car1","angle":45,"seconds":12}},"timeout":{"initial":60,"baseline":90}},{"name":"t2_wait_for_green","instruction":"Wait for green.","goal":{"op":"call","name":"wait_for_green","args":{"zone":{"kind":"crossing_side","id":"crossing_1","side":"end","inset":1.0,"r":2.0},"signal":"signal_1"}},"timeout":{"initial":60,"baseline":90},"after":["t1_look"]},{"name":"t3_cross","instruction":"Cross the street.","goal":{"op":"call","name":"cross","args":{"far_zone":{"kind":"crossing_side","id":"crossing_1","side":"start","inset":1.0,"r":2.0}}},"safety":[{"op":"call","name":"obey_signal","args":{"zone":{"kind":"crossing","id":"crossing_1"},"signal":"signal_1"}},{"op":"call","name":"collision_free","args":{"entity":"Car1","r":0.3}}],"timeout":{"initial":60,"baseline":90},"after":["t2_wait_for_green"]}]}
```
```python
from usg.dsl import *
scenario = ScenarioBuilder("scenario", MAP, scenario_type="custom")
scenario.user(Place(-1.9, 4.1).facing(MAP.place("crossing_1")))
scenario.signal_cycle("crossing_1", green=10, red=25, initial="red")
scenario.approaching_vehicle("Car1", ["road_4"], meet="crossing_1", speed=7, model="car_white")
handles = scenario.apply_spec(SPEC)
```
