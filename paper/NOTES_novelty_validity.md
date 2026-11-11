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
- VERIFIED this session (abstract/project page level only, not full texts):
  - Text2Scenario (arXiv 2503.02911, Cai et al., Beihang): LLM parses text, picks components from a hierarchical scenario repository, links them in a DSL corpus; CARLA; pedestrians appear as actors; evaluation is qualitative (24+20 demo scenarios, "most match expectations"), no metrics. Output format NOT confirmed as .xosc (earlier note said .xosc: unverified, do not write it).
  - LLM4AV (Springer chapter 2026): paywalled/redirected, full text NOT read. Only snippet-level facts (text -> DSL -> OpenSCENARIO on OpenDRIVE, multi-layer validator, pedestrian crossing example). Get the PDF via your institution before citing details.
  - Txt2Sce (arXiv 2509.02150): accident reports -> OpenSCENARIO seeds, DeepSeek + templates, 4,373 files, Autoware in CARLA; vehicle ego.
  - No arXiv paper literally named "LLM4AV" turned up in search: check the exact title/authors before using the name.
- Expressiveness matrix (columns for you to fill after reading; Y/N from abstracts, "?" = unknown):
| system | ego is human pedestrian | real map input | goal+safety formulas w/ margins | standard export | map-validated repair loop | quantitative per-type eval |
|---|---|---|---|---|---|---|
| Text2Scenario | N | ? (repository) | N | ? (DSL) | ? | N (qualitative) |
| Txt2Sce | N | N | N | Y (xosc) | ? | Y (counts) |
| LLM4AV | N | Y (retrieval) | N | Y | Y | ? |
| ChatScene / ScenicNL | N | N | N (Scenic) | N | Y | Y |
| GUsT-3D / JaywalkerVR | Y (human) | N | N | N | N | N |
| USG (this work) | Y | Y (OSM) | Y | Y | Y | Y (per type, Wilson CI) |
- Rule: claim only the cells you verified in the full text.

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

## 5b. ABLATION RESULT (Sophia, 25 prompts x 3 reps, same Qwen3.5-4B, model tier only) - IMPORTANT, CHANGES THE STORY
| level | accepted (Wilson 95%) | first-try | adherent |
|---|---|---|---|
| L0 script + helpers | 42/75 (45-67%) | 36 | 35 |
| L1 spec from library + world script | 50/75 (55-76%) | 19 | 36 |
| L2 + own defs | 39/75 (41-63%) | 11 | 31 |
- Per type accepted (L0/L1/L2, of 9; mixed of 12): cpath 9/5/1, dep_comp 3/6/5, dyn_nav 9/8/5, env_con 4/7/4, indep_comp 3/9/7, mixed 4/2/2, ptp_env 4/7/9, ptp_road 6/6/6.
- Honest reading: L2 is NOT the best level with this 4B model. L1 is best overall (50/75); L0 beats L2 on corridor-path and dynamic-navigation types (easy helpers), L2 wins only on ptp_env. L2 has the lowest first-try (11) = own definitions cost the small model extra errors.
- Intervals overlap (n=75) so do not claim L1 > L2 strongly; a paired test per prompt would be the right check.
- Consequences for the paper: (a) the claim "model-written definitions help" is NOT supported by this data, drop it or report as a negative/neutral result; (b) the contribution is the typed spec language + validator, not L2; (c) decide whether the headline system is L1 (best number) - but the per-type table was built on L2, so say which and why, and disclose that the choice of L2 was made BEFORE the ablation; (d) L0 high acceptance is partly because its helpers hide the spec: compare adherence+first-try, not accepted alone.
- Caveat: ablation prompts = the tuned prompts (pilots), so all levels have seen the same development.

## 5c. HELD-OUT MAP: Grenoble city centre (L2, 25 prompts x 3, same model, never used in development; prompts identical to Sophia, all 25 applicable)
| | accepted | first-try | adherent |
|---|---|---|---|
| Grenoble L2 | 35/75 (47%) | 6 | 22 |
| Sophia L2 (dev) | 39/75 (52%) | 11 | 31 |
- Per type accepted (of 9; mixed of 12): cpath 4, dep_comp 5, dyn_nav 4, env_con 2, indep_comp 6, mixed 3, ptp_env 7, ptp_road 4. Every type has at least 2 accepted.
- Reading: no collapse on an unseen, much denser map (305 crossings, 70 signals vs Sophia's few) = acceptance generalises; first-try and adherence are lower (6 vs 11; 22 vs 31), so the dev-set numbers are somewhat optimistic. Say this in threats to validity. Difference in accepted (35 vs 39) is well inside the CIs.
- Paris centre run pending (grenoble file also holds baseline rows: filter level == 2).

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
