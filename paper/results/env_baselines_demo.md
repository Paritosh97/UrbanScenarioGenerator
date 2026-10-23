# Reference policies in the headless environment

> **Demo run, two areas only** (Sophia Antipolis = test split, synthetic city = train split; 45 reference-script scenarios, 4 variants per type and map).
> Regenerate on all five areas and the LLM-generated scenarios with `scripts/eval_baselines.py` (see `docs/EVALUATION.md`).
>
> **Reading it honestly:** the map-blind `straight` policy solves almost as many reference scenarios as the scripted `route` walker (98% vs 96%), and the
> two failures of `route` are in `cpath` and `dep_comp` on Sophia. So the reference-script scenarios mostly separate *random* from *goal-directed* behaviour; they do
> not yet separate map-aware from map-blind behaviour, because they contain no traffic lights and little traffic. The harder tasks (signals, `look_at`, several
> movers) come from the L1/L2 generations and must be added before the dataset can be called a discriminating benchmark. `dyn_nav` is the one type where
> `straight` already breaks safety rules (20% cost).

45 scenarios; random policy over 5 seeds. `success` = every task of the scenario completed without breaking a rule (Wilson 95% interval); `cost` = share of episodes that broke a safety rule; `return` = mean episode return.

| group | policy | episodes | success | cost | return |
|---|---|---|---|---|---|
| all | route | 45 | 96% [85, 99] | 2% | 2.28 |
| all | straight | 45 | 98% [88, 100] | 2% | 2.34 |
| all | random | 225 | 17% [13, 23] | 24% | -0.07 |
| map:sophia_antipolis | route | 26 | 92% [76, 98] | 4% | 2.24 |
| map:sophia_antipolis | straight | 26 | 96% [81, 99] | 4% | 2.35 |
| map:sophia_antipolis | random | 130 | 21% [15, 29] | 23% | 0.06 |
| map:synthetic | route | 19 | 100% [83, 100] | 0% | 2.32 |
| map:synthetic | straight | 19 | 100% [83, 100] | 0% | 2.33 |
| map:synthetic | random | 95 | 13% [7, 21] | 24% | -0.26 |
| split:test | route | 26 | 92% [76, 98] | 4% | 2.24 |
| split:test | straight | 26 | 96% [81, 99] | 4% | 2.35 |
| split:test | random | 130 | 21% [15, 29] | 23% | 0.06 |
| split:train | route | 19 | 100% [83, 100] | 0% | 2.32 |
| split:train | straight | 19 | 100% [83, 100] | 0% | 2.33 |
| split:train | random | 95 | 13% [7, 21] | 24% | -0.26 |
| type:cpath | route | 8 | 88% [53, 98] | 12% | 1.63 |
| type:cpath | straight | 8 | 100% [68, 100] | 0% | 2.02 |
| type:cpath | random | 40 | 20% [10, 35] | 80% | 0.07 |
| type:dep_comp | route | 5 | 80% [38, 96] | 0% | 3.56 |
| type:dep_comp | straight | 5 | 100% [57, 100] | 0% | 4.04 |
| type:dep_comp | random | 25 | 0% [0, 13] | 0% | -0.06 |
| type:dyn_nav | route | 5 | 100% [57, 100] | 0% | 2.01 |
| type:dyn_nav | straight | 5 | 80% [38, 96] | 20% | 1.48 |
| type:dyn_nav | random | 25 | 24% [11, 43] | 60% | 0.14 |
| type:env_con | route | 4 | 100% [51, 100] | 0% | 2.01 |
| type:env_con | straight | 4 | 100% [51, 100] | 0% | 2.01 |
| type:env_con | random | 20 | 45% [26, 66] | 30% | 0.79 |
| type:indep_comp | route | 8 | 100% [68, 100] | 0% | 3.00 |
| type:indep_comp | straight | 8 | 100% [68, 100] | 0% | 3.00 |
| type:indep_comp | random | 40 | 0% [0, 9] | 0% | -0.81 |
| type:ptp_env | route | 8 | 100% [68, 100] | 0% | 1.93 |
| type:ptp_env | straight | 8 | 100% [68, 100] | 0% | 1.92 |
| type:ptp_env | random | 40 | 15% [7, 29] | 0% | -0.29 |
| type:ptp_road | route | 7 | 100% [65, 100] | 0% | 2.01 |
| type:ptp_road | straight | 7 | 100% [65, 100] | 0% | 2.01 |
| type:ptp_road | random | 35 | 29% [16, 45] | 0% | 0.18 |
