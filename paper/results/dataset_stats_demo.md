# Dataset statistics (demo: Sophia Antipolis + synthetic city only)

69 scenarios on 2 maps; 31 train / 38 test (split by map).

## Scenarios per map and type

| map | split | cpath | dep_comp | dyn_nav | env_con | indep_comp | look_cross | ptp_env | ptp_road | signal_cross | signal_traffic | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sophia_antipolis | test | 4 | 4 | 4 | 3 | 4 | 4 | 4 | 3 | 4 | 4 | 38 |
| synthetic | train | 4 | 1 | 1 | 1 | 4 | 4 | 4 | 4 | 4 | 4 | 31 |

## Constraint axes (number of scenarios per value)

| axis | values (count) |
|---|---|
| composition | ordered: 13, single: 48, unordered: 8 |
| dynamic | movers: 21, none: 48 |
| path | corridor: 8, free: 61 |
| signal | none: 53, obeyed: 16 |
| static | none: 65, obstacles: 4 |
| surface | crossing: 13, road: 9, walkable: 47 |

## Size and difficulty

- tasks per scenario: mean 1.38; entities: mean 0.49; vehicles: mean 0.49; signals: mean 0.23
- horizon (s): mean 153.22
- nominal walker satisfies every task: 68/69
- nominal goal margin: mean 1.62; nominal safety margin: mean 5.52
- sources: reference 45, reference_spec 24
