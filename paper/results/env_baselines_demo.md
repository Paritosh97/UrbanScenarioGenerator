# Reference policies in the headless environment

> **Demo run, two areas only** (Sophia Antipolis = test split, synthetic city = train split; 69 scenarios: the seven reference scripts and three
> specification-based scenarios with traffic lights, a look rule and a moving car; 4 variants per type and map, duplicates removed).
> Regenerate on all five areas and on LLM-generated scenarios with `scripts/eval_baselines.py` (see `docs/EVALUATION.md`).
>
> **Reading it honestly.**
> * Overall: scripted route walker 97%, map-blind straight-line walker 75%, random 12%.
> * **The traffic-light scenarios (`signal_cross`, `signal_traffic`) separate map-aware from map-blind behaviour:** the scripted walker solves 8/8 and 8/8, the
>   straight-line walker 0/8 and 0/8 (it walks onto the crossing on red: cost 100%), random 0%.
> * `look_cross` does **not** separate them (straight 100%): the car passes in front of the waiting participant, so a fixed gaze satisfies the look rule
>   incidentally. The rule needs a tighter time window or a start pose that makes looking necessary.
> * The scripted walker is not perfect in closed loop: its failures are type:cpath 88% [53, 98] (8 episodes), type:dep_comp 80% [38, 96] (5 episodes) (a rule violation), although the offline nominal walker accepted
>   them. Its yielding is crude; do not read its success rate as an upper bound of what is solvable.
> * The seven reference scripts alone (the first demo) were easy: straight 98% vs route 96%.

69 scenarios; random policy over 5 seeds. `success` = every task of the scenario completed without breaking a rule (Wilson 95% interval); `cost` = share of episodes that broke a safety rule; `return` = mean episode return.

| group | policy | episodes | success | cost | return |
|---|---|---|---|---|---|
| all | route | 69 | 97% [90, 99] | 1% | 2.30 |
| all | straight | 69 | 75% [64, 84] | 25% | 1.73 |
| all | random | 345 | 12% [9, 16] | 41% | -0.08 |
| map:sophia_antipolis | route | 38 | 95% [83, 99] | 3% | 2.28 |
| map:sophia_antipolis | straight | 38 | 76% [61, 87] | 24% | 1.81 |
| map:sophia_antipolis | random | 190 | 15% [11, 21] | 39% | 0.03 |
| map:synthetic | route | 31 | 100% [89, 100] | 0% | 2.33 |
| map:synthetic | straight | 31 | 74% [57, 86] | 26% | 1.64 |
| map:synthetic | random | 155 | 8% [4, 13] | 44% | -0.23 |
| split:test | route | 38 | 95% [83, 99] | 3% | 2.28 |
| split:test | straight | 38 | 76% [61, 87] | 24% | 1.81 |
| split:test | random | 190 | 15% [11, 21] | 39% | 0.03 |
| split:train | route | 31 | 100% [89, 100] | 0% | 2.33 |
| split:train | straight | 31 | 74% [57, 86] | 26% | 1.64 |
| split:train | random | 155 | 8% [4, 13] | 44% | -0.23 |
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
| type:look_cross | route | 8 | 100% [68, 100] | 0% | 3.03 |
| type:look_cross | straight | 8 | 100% [68, 100] | 0% | 3.06 |
| type:look_cross | random | 40 | 5% [1, 17] | 22% | 1.02 |
| type:ptp_env | route | 8 | 100% [68, 100] | 0% | 1.93 |
| type:ptp_env | straight | 8 | 100% [68, 100] | 0% | 1.92 |
| type:ptp_env | random | 40 | 15% [7, 29] | 0% | -0.29 |
| type:ptp_road | route | 7 | 100% [65, 100] | 0% | 2.01 |
| type:ptp_road | straight | 7 | 100% [65, 100] | 0% | 2.01 |
| type:ptp_road | random | 35 | 29% [16, 45] | 0% | 0.18 |
| type:signal_cross | route | 8 | 100% [68, 100] | 0% | 2.01 |
| type:signal_cross | straight | 8 | 0% [0, 32] | 100% | -0.64 |
| type:signal_cross | random | 40 | 0% [0, 9] | 100% | -0.67 |
| type:signal_traffic | route | 8 | 100% [68, 100] | 0% | 2.01 |
| type:signal_traffic | straight | 8 | 0% [0, 32] | 100% | -0.65 |
| type:signal_traffic | random | 40 | 0% [0, 9] | 100% | -0.67 |
