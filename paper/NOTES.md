# Notes for writing the paper (revision aids, NOT paper text)

Scope and RQs: see the FINAL SCOPE block at the top of `paper.md`. Method detail: `METHOD.md`. Final numbers: `results/` after the run.

## 1. The method in one breath (to say it aloud)
* Input: OSM area + text prompt. Output: scenario file (OpenSCENARIO + `<VRTask><Spec>`, OpenDRIVE) played in a WebXR / first-person player; the human is the pedestrian.
* One task form = goal formula + safety formulas + timeout. Atoms return signed margins (metres, degrees, m/s). Combinators: and, or, not, implies, eventually, always, until, then, prev. Library operators: reach, cross, wait_for_green, obey_signal, collision_free, look...
* Scenario type is read off the formulas along 6 axes (surface, path, static, dynamic, signal, composition); the 7 types are named points on them.
* Generation (Qwen3.5-4B, local): stage A writes the specification (data), stage B writes a short world script (entities, signals) that applies it. Levels: L0 script + helpers, L1 specification from the library, L2 + own definitions.
* Validation: schema, grounding on the map, sandboxed script, participant starts on walkable ground, timeouts fit the route, nominal walker (1.2-1.3 m/s) satisfies all tasks, esmini loads the files (69/69).
* Repair: if the script keeps failing but the specification was accepted, the system builds the world itself and raises too-short timeouts. Reported as its own tier ("assisted"), never counted as a model success.

## 2. What "valid" does and does not mean
* Valid = passes our checks. It is not proof that the scenario matches the prompt: `adherent` is axis-level; the rater study (RQ4) is the semantic check.
* Never claim "100% valid", "first", or "complete". Say "to our knowledge, in the sources we searched".

## 3. Positioning (compare by expressiveness, not head to head)
Verified at abstract / project-page level only; fill the cells from full texts before writing them.
| system | ego is human pedestrian | real map input | goal + safety formulas with margins | standard export | map-validated repair loop | quantitative per-type evaluation |
|---|---|---|---|---|---|---|
| Text2Scenario (arXiv 2503.02911) | N | ? (component repository) | N | ? (DSL; xosc not confirmed) | ? | N (qualitative, 24+20 demos) |
| Txt2Sce (arXiv 2509.02150) | N | N | N | Y (xosc seeds) | ? | Y (counts) |
| LLM4AV (Springer chapter 2026, paywalled, NOT read) | N | Y (retrieval) | N | Y | Y | ? |
| ChatScene / ScenicNL | N | N | N (Scenic) | N | Y | Y |
| GUsT-3D / JaywalkerVR | Y (human) | N | N | N | N | N |
| this work | Y | Y (OSM) | Y | Y | Y | Y (per type, Wilson CI) |
* Other groups to cite (see `paper.md` section 3): HASCO, NL2Scenic / Chat2Scenic, grammar-constrained IR, KGST NL->STL, TR2MTL, NavAI / LLMR / Text2VRScene, MetaUrban / UrbanWorld / CityX.
* No arXiv paper literally named "LLM4AV" turned up in search: check the exact title and authors.
* Safe sentence: existing LLM-to-scenario work targets vehicle-under-test scenarios; we generate guided tasks for a human pedestrian, grounded in a real map and played in VR or first person.

## 4. Claims, strongest first (hedge all)
1. Typed task specification with signed margins shared by generator, validator, player (one monitor, parity tested).
2. Pedestrian-ego guided tasks as the generation target, with standard-format export.
3. Honest accounting: model-only vs assisted tiers; validator-derived adherence.
4. NOT claimable: that own definitions (L2) help; that a small model is reliable on dense maps; generalisation to unseen maps.

## 5. Threats to validity (write all)
Author-written prompts; one 4B model; 2 repetitions (wide intervals); axis-level adherence; idealised nominal walker; repair, "any order" rule, duplicate-task check and four harness fixes (signal ids, sandbox limit, JSON repair, speed) were designed after earlier runs (METHOD.md section 8); same prompt templates as in development; assisted scenarios partly system-built; rating covers prompt match, not task performance; no study with participants performing tasks.

## 6. Why failures happen (use for a short failure paragraph)
From the first full run (v1, development record) and earlier runs: about a third of the L1/L2 failures were harness faults, now fixed (METHOD.md section 8: signal ids rejected by `signal_cycle`, 30 s sandbox limit on Paris, malformed JSON with a misplaced bracket repeated until the agent gave up); the rest is model weakness. Most failures come after the specification is accepted: world script rejected (start not on walkable ground, timeout shorter than the route, script timeout on a dense map, named entity never created, wrong signal call), or the task as written breaks a safety rule for the nominal walker, or the model never produces a specification. The final run logs the full rejection text (`last_feedback`) so this can be counted properly.

## 7a. Final numbers (v6 run, 13-14 Nov 2026; details: METHOD.md section 9.0, `paper/results/summary.md`; v4 and earlier are development records in `paper/results/old_*`)
* 100 runs per level (2 maps x 25 prompts x 2 repetitions), all three levels on the SAME harness. Model-only accepted: L0 62 (52-71), L1 71 (61-79), L2 68 (58-76); assisted 0 / 26 / 26; adherent 57 / 67 / 65. Sign tests on accepted: L1 vs L2 p = 0.61, L0 vs L2 p = 0.33, L0 vs L1 p = 0.28. The types dyn_nav, mixed, env_con, ptp_env were re-run after two plumbing fixes (v6), the rest is the v5 run. No level differs significantly.
* What you can say: the three numbers with intervals and the tests; that the repair tier raises valid output at L1/L2 (L0 has none); the per-type table (strong: ptp_road, cpath, indep_comp 11/12 at L2; weak: env_con 6, dep_comp 6, mixed 8/16, dyn_nav 5/12). What you cannot say: that spec levels beat the script level, or that definitions (L2) help.
* Why runs fail (read from `last_feedback`; validator errors on real defects, not evaluation artefacts): dyn_nav 20 of 24 L1/L2 runs: the world script wrote `when_task_starts(None)` (9) or other script errors; mixed: unknown signal/entity names; env_con/ptp_env: scripts using `Place` attributes that do not exist; dep_comp/indep_comp: goals 500-1100 m away with too short a timeout. The v6 fixes (None = first task; `Place` hint) raised dyn_nav L2 0 -> 5 of 12; L0 rows of the same types moved by up to 4 runs without any relevant change, so treat small differences as noise.
* Adherence caveat: 19 'mixed' runs have the requested axes and atoms but split 'wait, then cross' into two ordered tasks, which the strict test counts as a composition mismatch; report strict adherence and the secondary recall.
* Honest history: five full runs (v1 28/33 L1/L2 accepted -> v2 47/46 -> v3 39/48 -> v4 55/63 -> v6 71/68). The steps are harness fixes found by reading failures of the same prompts, not a better model. Disclose: the `cross` axis consistency fix, the harness-supplied grounded ids/crossings/corridors, and development on the same 50 prompts.

## 7. Outline you can write from
1. Problem and gap. 2. Related work (short + matrix). 3. Task model and language (RQ1). 4. Framework: map, generation, validation, repair tier, player. 5. Evaluation: setup, per-type table, L0/L1/L2 table, tier/failure table, rater study, threats. 6. Discussion and limits. 7. Conclusion. Appendix: prompts, development history.
