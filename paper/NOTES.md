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

## 7a. Final numbers (v2 run, 13 Nov 2026; details and tables: METHOD.md section 9.0, `paper/results/summary.md`)
* 100 runs per level (2 maps x 25 prompts x 2 repetitions). Model-only accepted: L0 47, L1 47, L2 46 (no difference, all sign tests p >= 0.8). Valid output with the repair tier: L1 73, L2 70 (L0: 47, no tier). First try: 39 / 10 / 8. Adherent: 41 / 45 / 40.
* What you can say: the specification levels give the same model-only acceptance as writing scripts directly and add a repair tier that lifts valid output to 70-73%; the assisted scenarios keep the model's task rules but have a system-built world. What you cannot say: that L1/L2 raise acceptance, that definitions (L2) help, that the small model is reliable on every type (dyn_nav 2/12, cpath 1/12 model-only at L2).
* Honest history: the first full run (v1) gave L1 28 and L2 33 accepted; four harness faults (signal ids, 30 s sandbox limit, malformed-JSON giving up, slow map code) were found by reading its failures and fixed, then L1 and L2 were re-run (METHOD.md section 8). Say so in the paper; v1 is not reported as a result.
* Not analysed: 8 L2 runs still end as "model stopped calling tools"; 13 L2 runs end as "too many rejected scripts" without a rescue (causes not yet counted; in the pilot they were safety rules that the nominal walker breaks and missing entities or user in the world script).

## 7. Outline you can write from
1. Problem and gap. 2. Related work (short + matrix). 3. Task model and language (RQ1). 4. Framework: map, generation, validation, repair tier, player. 5. Evaluation: setup, per-type table, L0/L1/L2 table, tier/failure table, rater study, threats. 6. Discussion and limits. 7. Conclusion. Appendix: prompts, development history.
