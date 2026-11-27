# Problems to solve, in the order of execution (26 Nov 2026; planning notes, not paper text)

Rule: a stage starts only when the checks ("done when") of the stages before it pass. All pilot results (base, SFT, RL) were obtained **before** these fixes
and with large maps; they are development records, not results for the paper.

Tags: **[verified]** seen in code or data; **[design]** decision or requirement; **[open]** needs a decision or a measurement.

## Stage 1. Map window and map summary (CPU)
**Map part of the user prompt: template frozen 27 Nov 2026** (`paper/p1/ALGORITHM.md`, `src/usg/training/window.py`).

| id | problem | status | what is left |
|---|---|---|---|
| P1 | No layout in the map summary | **fixed** | tests of the last two fixes not yet run |
| P2 | Only things near the map centre could be referred to | **fixed** in the new template: everything in the window is listed | - |
| P3 | Maximum map size 30 x 30 m | partly | windows done; the simulator must show the same window; check full prompt + reply length |
| P4 | Which tasks and vehicle starts work in 30 m (cars start outside the window) | open | decide with the generator; list of kinds with one valid example each |
| P5 | Prompt hints contradict the reference | partly: no hints in the new template | the pipeline still builds the old prompt |
| P6 | Maps are all European | open | add non-European areas; split by area |
| P7 | Map summary not validated | partly: automatic completeness test | run tests; geometry question check (P33) |
| P32 | New map text and window cleaning are not connected | open | generator, checks and simulator use the window and its removal log |
| P33 | Unknown whether a 2B model understands coordinates in text | open | geometry questions before and after SFT; optional ablation with stated relations |
| P34 | 4 of 16 areas not yet downloaded with the new query (Berlin, Nantes, Strasbourg, Vienna) | open, low priority | rerun `scripts/fetch_train_maps.py` |

Template alternatives (JSON, stated relations, geometry embeddings) are not compared; do not call the format optimal.

## Stage 2. Task language and levels
| id | problem | fix | done when |
|---|---|---|---|
| P8 | [verified] L1 references mostly use single library calls (`then` mainly for signals) | Decide which compositions L1 data must contain | operator and depth distribution reported |
| P9 | [verified] L1 references leave the start automatic for walking / visiting kinds; L0 sets it (`sampler.py:120-232`) | Explicit start at both levels | every reference has an explicit start |
| P10 | [verified] L0 cannot express a gaze goal (`sampler.py:27`) | Add the helper, or state the limit and compare shared kinds only | decision written |

### Decisions of 27 Nov 2026 (P4, P8-P10): decided, not yet implemented
* **P4:** all task kinds stay (walk to object, road point, corridor, parked cars, moving car, visits, signal, signal + car, look then cross). Moving cars start outside
  the window on the same road; the request states direction, speed and trigger; the generator computes the start distance so that the car meets the walker; the simulator
  shows road and car beyond the window. More signalised windows are needed (16% of windows have one).
* **P8:** tasks are built from goal stages (1-3: reach, cross, wait for green, look, hold), safety rules (0-3: obey signal, no collision, keep distance, corridor,
  stay on sidewalk, walking speed) and order (one, ordered, any order). Some combinations are held out for testing.
* **P9:** explicit start position at both levels, stated in the request; no automatic start in references.
* **P10:** option A: add L0 helpers (look_at, hold, keep_clear). Open: wait-for-green stage, stay-on-sidewalk and walking-speed rules have no L0 helper yet.
  L0 and L1 are compared on tasks both can express.

**Update 27 Nov:** L0 helpers added (wait_for_green, look_at, hold; options keep_clear, stay_on, pace): syntax checked only, not run.
P11, P12, P13, P16: scenario record approved (`paper/p3/RECORD.md`; car starts at scenario start; letting it pass is allowed).
Implemented, **never run** (imports only): `approaching_vehicle` helper; `localise()` (part of P32); record sampler, request and L0/L1 reply rendering,
one reference per (window, request), field-by-field verifier (`src/usg/training/records.py`). Not connected to `scripts/train_data.py` or the system prompt.

**Update 27 Nov (later):** generator completed and run on 4 areas (284 records, 63% of checked records pass); notes: `paper/p3/GENERATION.md`.
Done: P11-P13, P16; first version of P14 (fixed phrasings) and P15 (combinations, held-out sets). Open: walking-graph detours reject valid records (P17), few
signal tasks (P20), verifier test (P18), training scripts still read the old data. The older pipeline tests have not been run.

**Decision 27 Nov (replaces the earlier L0/L1 decisions, including P10 and the joint model):** L0 is dropped. L1 is the only method and is not restricted
to what L0 can express. Not yet implemented: generator, prompt and verifier still produce and check both levels with the shared types only.

**Update 27 Nov (dataset):** L1-only generator written and run: 10008 records for Paris and Munich (`paper/p3/DATASET.md`, `train/data_city/`).
Done for this data: P8-P9, P11-P17, P20 (sizes fixed). Partly: P18 (right and constructed wrong replies only), P3 (simulator view not checked), P32.
Open next: training scripts still read the old data and the old reward; few signal tasks; human check (P22).

## Stage 3. Synthetic data generator (CPU)
| id | problem | fix | done when |
|---|---|---|---|
| P11 | [verified] The crossing is drawn at random and never identified in the request (`sampler.py:109-118`); about 89% of rows with a hint use another crossing; road points match the hint in 3 of 312 | Every choice in the reference is stated in the request or fixed by a stated rule | automatic check: each reference field traces to the request |
| P12 | [design] Requests are not descriptive | State start position, targets, crossing, order, vehicles (type, from where, speed, trigger), signals, safety rules, timing | field coverage report |
| P13 | [verified] 306 extra training rows share map, level and request with another reference | One reference per (window, level, request) | zero conflicts |
| P14 | [verified] 1825 distinct requests in 4373 examples; 4-6 fixed sentences per kind (`sampler.py:120-274`) | Compose requests from parts; paraphrase; re-check paraphrases against the fields | distinct-wording count; sample check |
| P15 | [verified] One fixed task structure per kind | Combine constraints (order, signal, vehicle, parked cars, corridor, gaze); hold out some combinations for testing | combination table |

## Stage 4. Verifier: does the scenario make sense for this map and request? (CPU)
| id | problem | fix | done when |
|---|---|---|---|
| P16 | [verified] Checks show that a scenario is executable, not that all task information is right (request grounding is keyword based) | Compare field by field with the structured intent: start, crossing, targets, order, vehicles, signals, rules, timing | each field has a check and a test |
| P17 | [open] Plausibility on the map | Start on walkable ground, route exists, crossing is the described one, vehicle on its road in a legal direction and actually meeting the walker | checks plus tests |
| P18 | [open] The verifier itself is unvalidated | Feed deliberately wrong scenarios; hand-check accepted and rejected samples | false accept and false reject rates reported |
| P19 | [design] Tasks run in our own simulator (custom OpenSCENARIO elements) | State it in the paper | sentence in method and limitations |

## Stage 5. Datasets and test set
| id | problem | fix | done when |
|---|---|---|---|
| P20 | [open] Sizes (earlier plan: SFT set A 10k, RL pool B 4k) must be revisited for 30 m windows | Generate; measure rejection rates and variety | frozen files with hashes |
| P21 | [design] Hand-verified test set of new requests on unseen areas. The 50 old prompts were used in development and do not fit 30 m windows | Choose and verify by hand (best: requests written by other people); note required properties before seeing outputs | frozen and hashed before any model run |
| P22 | [open] Error rate of the training data unknown | Hand-check a stratified sample (about 300); second annotator on a subset | error rate with interval, agreement |

## Stage 6. Base model and prompt
| id | problem | fix | done when |
|---|---|---|---|
| P23 | [open] Only one prompt (with one example) tried on the 2B base | Choose zero-shot / few-shot on validation; same prompt for base, SFT, RL | prompt frozen |

Update 27 Nov (training code): `train_model.py` reads `train/data_city` and the new prompt; `train_data.py` removed (backup `usg_bak_p1/before_ft/`).
Reward (`training/reward.py`): 1.0 if every verifier field is right, else 0.1 parses + 0.1 builds + 0.5 x weighted share right (goals 3, rules 2, others 1).
Limit 4096 tokens (longest example 3862); new tokens 1024, test_long 1700. SFT validates each epoch; sft and rl save the optimizer state.
RL defaults: 3 requests, 16 replies, 4 selected, 3 updates, clip 0.1, lr 3e-5, top-p 1.0. Nothing run yet (GPU memory: `train_model.py memcheck`).

## Stage 7. SFT
| id | problem | fix | done when |
|---|---|---|---|
| P24 | [verified] Pilot: 2000 examples, 1 epoch, resumed without optimizer state | Full run on set A; save optimizer state | validation scores per epoch |

## Stage 8. Hard-example selection
| id | problem | fix | done when |
|---|---|---|---|
| P25 | [design] Pool B is never used in SFT; low mean reward over several samples marks a request as hard; no second SFT | Score B; report how many are hard and how many never succeed | pool stored with rewards |

## Stage 9. RL
| id | problem | fix | done when |
|---|---|---|---|
| P26 | [verified] Reward compares with one reference; other valid answers score lower | Reward the required properties from the verifier (stage 4) | valid alternatives get full reward in tests |
| P27 | [verified] Pilots 1 and 2 (4 replies, 1 update) showed no gain; new settings (16 replies, 4 selected, 3 updates, no std division) improved 3 training prompts | Put the new settings in `train_model.py`, top-p 1.0, checkpoints with optimizer state, resume | short run shows learning |
| P28 | [open] Gain on unseen requests not shown | Check validation after each epoch; stop rule fixed before the run | decision recorded |

## Stage 10. Evaluation, release, paper
| id | problem | fix | done when |
|---|---|---|---|
| P29 | [verified] Automatic matching is lenient | Verifier fields plus blinded hand judgement | judgements stored |
| P30 | [open] One seed so far; inference columns (resampling, few-shot) undecided | At least 3 seeds for the main comparison; decide columns on validation | tables with intervals |
| P31 | [open] Release of data, generator, verifier, adapters, records | OpenStreetMap attribution (ODbL); check the Qwen3.5-2B licence; add LICENSE | release checklist done |

## Optional, after the main pipeline works
| id | item | note |
|---|---|---|
| P35 | Choose the map window from the request alone (search stored windows by required features) | scenario model needs no extra training; request-to-features by rules or prompting first; rough estimate 4-6 days |

