# Replay of the recorded failures through the safety nets

40 runs of `grenoble_l2.jsonl` (level 2, map grenoble) that the model did not finish. Safety nets: `world`.

| outcome | runs | adherent to the request |
|---|---|---|
| assisted | 9 | 5 |
| fallback | 0 | 0 |
| none | 31 | - |

Valid output after the nets: 9/40. The model alone finished 35/75 runs of this level; the runs finished by `assisted` or `fallback` are NOT model successes and are reported separately.

| type | assisted | fallback | none |
|---|---|---|---|
| cpath | 0 | 0 | 5 |
| dep_comp | 0 | 0 | 4 |
| dyn_nav | 4 | 0 | 1 |
| env_con | 0 | 0 | 7 |
| indep_comp | 0 | 0 | 3 |
| mixed | 4 | 0 | 5 |
| ptp_env | 1 | 0 | 1 |
| ptp_road | 0 | 0 | 5 |

(772 s)
