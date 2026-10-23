# Dataset statistics (demo: Sophia Antipolis + synthetic city only)

45 scenarios on 2 maps; 19 train / 26 test (split by map).

## Scenarios per map and type

| map | split | cpath | dep_comp | dyn_nav | env_con | indep_comp | ptp_env | ptp_road | total |
|---|---|---|---|---|---|---|---|---|---|
| sophia_antipolis | test | 4 | 4 | 4 | 3 | 4 | 4 | 3 | 26 |
| synthetic | train | 4 | 1 | 1 | 1 | 4 | 4 | 4 | 19 |

## Constraint axes (share of scenarios with a non-default value)

| axis | values (count) |
|---|---|
| composition | ordered: 5, single: 32, unordered: 8 |
| dynamic | movers: 5, none: 40 |
| path | corridor: 8, free: 37 |
| signal | none: 45 |
| static | none: 41, obstacles: 4 |
| surface | crossing: 13, road: 9, walkable: 23 |

## Size and difficulty

- tasks per scenario: mean 1.40; entities: mean 0.40; vehicles: mean 0.40; signals: mean 0.00
- horizon (s): mean 162.50
- nominal walker satisfies every task: 44/45
- nominal goal margin: mean 1.77; nominal safety margin: mean 2.18
- sources: reference 45
