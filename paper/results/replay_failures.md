# Replay of the recorded failures through the safety nets

36 runs of `sophia_l2.jsonl` (level 2, map sophia_antipolis) that the model did not finish. Safety nets: `fallback`; every rescued scenario must also load and run in esmini.

| outcome | runs | adherent to the request |
|---|---|---|
| assisted | 2 | 1 |
| fallback | 34 | 12 |
| none | 0 | - |

Valid output after the nets: 36/36. The model alone finished 39/75 runs of this level; the runs finished by `assisted` or `fallback` are NOT model successes and are reported separately.

| type | assisted | fallback | none |
|---|---|---|---|
| cpath | 0 | 8 | 0 |
| dep_comp | 0 | 4 | 0 |
| dyn_nav | 1 | 3 | 0 |
| env_con | 0 | 5 | 0 |
| indep_comp | 0 | 2 | 0 |
| mixed | 1 | 9 | 0 |
| ptp_road | 0 | 3 | 0 |

(247 s)
