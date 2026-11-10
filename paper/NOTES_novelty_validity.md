# Notes for you (revision aids, NOT paper text)

Status: single-stage ("2a") run still in progress when written; section 5 gets filled in once it finishes (paper/results/sophia_l2a.jsonl).

## 1. Pipeline in one breath (to say it aloud)
- Input: OSM area + text prompt. Output: OpenSCENARIO (+ `<VRTask>/<Spec>`) + OpenDRIVE, played with a live monitor.
- One task form = goal formula + safety formulas. Atoms carry signed margins; combinators; STD_LIB; L2 = model adds own `defs`.
- Two-stage (L2): model writes spec THEN a world script. Single-stage (2a): model writes spec only; harness builds world from named entities/signals (`assist.world_script`) and validates; errors come back as spec errors.
- Validation: schema -> grounding on map -> sandboxed script -> esmini load -> nominal-walker solvability (monitor margin).
- Tiers: model | assisted | fallback. Only `model` counts as accepted.

## 2. Validity: what is actually verified (and what is not)
- Verified: monitor parity Python/TS (tests), 200 unit tests, esmini loads 53/69 (signal actions were the failure; fixed with numeric ids), nominal walker satisfies all tasks.
- NOT verifiable to 100%: "valid" = passes our checks, not semantically faithful to the prompt. `adherent` is axis-level only, never full semantic match -> say so. No human rating yet.
- Never claim "first"/"complete". Claim: "to our knowledge, in the sources we searched".

## 3. SOTA positioning (compare by expressiveness, not head to head)
- Txt2Sce, Text2Scenario, ChatScene, ScenicNL / NL2Scenic, Chat2Scenic: LLM -> scenario for ego VEHICLE under test; no pedestrian ego, no goal+safety formula with margins.
- HASCO / SAE grammar-constrained IR: constrained decoding to an IR; closest in spirit (typed intermediate), but targets vehicles.
- KGST (NL -> STL), TR2MTL: NL -> temporal logic; no map grounding or standard export.
- GUsT-3D, JaywalkerVR, LLM4AV, NavAI/LLMR/Text2VRScene: VR pedestrian studies / scene generation; no formal rules + OpenSCENARIO export.
- Gap statement: text+map -> validated pedestrian guided tasks with robustness semantics, standard-format export, human or synthetic ego.
- To do: read LLM4AV and Text2Scenario in full before finalising; build expressiveness matrix (systems x 7 types x 6 axes).

## 4. Novelty claims (hedged), strongest to weakest
1. Task spec language with signed margins shared by generator, validator, player and agent (one monitor, parity tested). Strongest.
2. Pedestrian-ego guided tasks as the generation target, exported to OpenSCENARIO/OpenDRIVE.
3. Model-written definitions (L2) checked by the type system. Weak unless ablation L1 vs L2 shows gain -> run it or drop the claim.
4. Single-stage harness-built world: engineering simplification, not a novelty.

## 5. Can it be simplified? (RESULT: single-stage 2a vs two-stage L2, same Qwen3.5-4B, 75 runs each)
| metric | L2 (two-stage) | 2a (spec only) |
|---|---|---|
| accepted | 39/75 | 33/75 |
| first-try | 11 | 18 |
| adherent | 31 | 23 |
- Per type accepted (L2 / 2a): cpath 1/5, dep_comp 5/7, dyn_nav 5/2, env_con 4/0, indep_comp 7/5, mixed 2/4, ptp_env 9/6, ptp_road 6/4 (of 9, mixed of 12).
- Reading: 2a is NOT better overall. It cuts retries (first-try 11 -> 18) but accepts fewer and loses adherence; env_con drops to 0 (model-written worlds were needed for those scenes), cpath improves.
- Decision: do NOT make 2a the default; keep L2 as the evaluated system. Report 2a as a variant/negative result (simplification does not help with this model). Differences at n=75 are within wide CIs: do not over-claim either way.
- Same model throughout: Qwen3.5-4B Q4_K_M.

## 6. Threats to validity (must be written)
- Prompts and map used during development (pilots 1-3 on same prompts) -> tuning on test; disclose pilots; add held-out map.
- Prompts written by the author. One model, one map, 3 reps, T=0.2.
- Fallback/assist tiers inflate `valid_output`; report model-tier only.
- Nominal walker is idealised (1.2-1.3 m/s, no noise).
- Axis-level adherence; no user study.
- Wilson CIs wide at n=3 per prompt.

## 7. Framing outline you can write from
1. Problem: authoring guided pedestrian tasks for VR/human-in-loop studies is manual.
2. Idea: tasks as typed formulas with margins -> one object serves generation, checking, play, agents.
3. Method: language, taxonomy as axes, pipeline, validator, repair loop.
4. Evaluation: Sophia map, 25 prompts x 3, per-type table; 2a vs 2.
5. Limits and threats (section 6 above).

## 8. Housekeeping
- The cloud branch added AI-written prose (paper/paper.tex sections, OUTLINE.md, refs.bib). You said you write the paper: delete or overwrite what you don't want.
