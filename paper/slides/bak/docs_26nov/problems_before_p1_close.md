# Problems to solve, in the order of execution (26 Nov 2026; planning notes, not paper text)

Rule: a stage starts only when the checks ("done when") of the stages before it pass. All pilot results (base, SFT, RL) were obtained **before** these fixes
and with large maps; they are development records, not results for the paper.

Tags: **[verified]** seen in code or data; **[design]** decision or requirement; **[open]** needs a decision or a measurement.

## Stage 1. Map window and map summary (CPU)
| id | problem | fix | done when |
|---|---|---|---|
| P1 | [verified] The summary has no layout: object counts, ids named in the request, a few crossings (`grounding.py:52,63`, `oneshot.py:83,103`) | Pass the layout: roads (shape, width, lanes, one-way), sidewalks, crossings, signals, objects, buildings, paths | the scene can be redrawn from the prompt text alone and matches the map |
| P2 | [verified] Only things near the map centre can be referred to (3 nearest objects per named type, 3 crossings per control type) | List everything inside the window | every object in the window is in the prompt |
| P3 | [design] Maximum map size **30 x 30 m** | Cut windows from OSM areas, re-centre coordinates, clip roads and buildings | token count measured on all windows; prompt + reply fit the length limit |
| P4 | [open] 30 m limits tasks: only short walks; a car at 5-10 m/s crosses the window in 3-6 s; the current vehicle route reaches 30 m before the crossing | Decide where vehicles start (outside the window or not) and which task kinds remain | list of supported kinds with one valid example each |
| P5 | [verified] Prompt hints ("For a crossing task use X", road-point example) disagree with the reference (`grounding.py:80-94`) | Remove the hints; the layout replaces them | no hint text in prompts |
| P6 | [design] Maps are all European | Add non-European areas; split train / validation / test by area, not by window | split file; no area in two splits |
| P7 | [open] The summary is not validated | Unit tests plus a top-down drawing made from the summary, compared by eye on a sample | windows checked, errors counted |

### P1 sub-problems (code: `src/usg/training/window.py`; algorithm: `paper/p1/ALGORITHM.md`; not yet connected to the pipeline)
| id | sub-problem | state (26 Nov, night) |
|---|---|---|
| P1.1 | Mixed window kinds | done (crossing, junction, street, pedestrian) |
| P1.2 | Coordinates | done |
| P1.3 | Roads | done |
| P1.4 | Sidewalks and paths | done for the model's data (compass names, merged paths, grouped stairs); **open: mapped OSM sidewalks are discarded by the import** |
| P1.5 | Crossings and signals | done |
| P1.6 | Junctions and road ends | done |
| P1.7 | Odd objects removed and logged, never moved | done in the window; the simulator must apply the same log |
| P1.8 | Buildings against OSM | **open: building relations are not downloaded** |
| P1.9 | Local ids with stored mapping | done |
| P1.10 | Text format | draft for approval |
| P1.11 | Validation | automatic completeness test against the map model (`tests/test_window.py`) |

## Stage 2. Task language and levels
| id | problem | fix | done when |
|---|---|---|---|
| P8 | [verified] L1 references mostly use single library calls (`then` mainly for signals) | Decide which compositions L1 data must contain | operator and depth distribution reported |
| P9 | [verified] L1 references leave the start automatic for walking / visiting kinds; L0 sets it (`sampler.py:120-232`) | Explicit start at both levels | every reference has an explicit start |
| P10 | [verified] L0 cannot express a gaze goal (`sampler.py:27`) | Add the helper, or state the limit and compare shared kinds only | decision written |

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
