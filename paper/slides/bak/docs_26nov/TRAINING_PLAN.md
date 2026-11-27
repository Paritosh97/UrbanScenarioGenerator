# Training plan: LLM to verifiable scenario specification (planning notes, not paper text)

Written Thu 26 Nov 2026, 14:30. **Experiments end Sun 29 Nov, 12:00. Then writing.**
Target: an ML paper (TMLR recommended; check current rules). Dataset published, checked by hand. No user study.

## 1. Question and claims to test
| id | question | evidence |
|---|---|---|
| Q1 | Can a 2B model produce accepted, request-matching scenarios in one shot? | base vs SFT vs SFT+RL |
| Q2 | Does online RL with verifier rewards add to SFT? | SFT vs RL; ablation without the match term |
| Q3 | Does the output level (L0 code, L1 specification, L2 own definitions) matter? | all of the above per level |
| Q4 | How much does a repair loop add, and does training reduce the need for it? | one shot vs repair for base, SFT, RL |
| Q5 | How much data is needed? | 500 / 1000 / 2000 / 4373 examples |

No claim that a level or a method is better unless the paired test supports it. A null RL result is reported.

## 2. Done (measured)
* Data: 13 training and 3 validation maps; 4373 training examples (all fit in 3000 tokens) and about 1040 validation examples, each accepted by the checks.
* Qwen3.5-2B, bf16, LoRA r=16: SFT 2.3 s per example, peak 11.8 GB allocated. Without a memory cap the run paged into system RAM and stalled
  (cap now 0.88). One-shot evaluation about 4-6 s per case (batch 8). RL 77-109 s per step (4 prompts x 4 replies), about 40 steps per hour.
* One-shot pilot, SFT on 2000 examples, one seed (default-script rule at L1/L2):

| 50 original prompts | L0 | L1 | L2 |
|---|---|---|---|
| base accepted / matching | 0 / 0 | 16 / 5 | 17 / 6 |
| SFT accepted / matching | 30 / 28 | 35 / 29 | 33 / 29 |

* Validation accepted: base 0/36, 8/40, 7/40; SFT 32/36, 31/40, 32/40.
* RL pilot (50 steps): running since 14:20; evaluation expected about 16:30.

## 3. Fixed protocol
* Same system prompt per level, greedy-free sampling at temperature 0.2, 900 new tokens, same checks for every model.
* L1/L2 default script when a reply has no python block (all models; flag `default_script` kept in every record).
* Repair condition: same runtime as one shot. If rejected, append the checker feedback and generate again, at most 3 replies. No tools.
  Report accepted after 1, 2, 3 replies. The deterministic repair tier is off.
* The full tool agent is **not** re-run with the 2B model (needs GGUF conversion, untested). The existing 4B agent results are a separate reference, not a controlled comparison.
* Test sets: (a) the 50 original prompts, marked as used in development; (b) a new held-out set (section 6). Final claims rest on (b).

## 4. Runs and GPU hours
Estimates from section 2; "per model" evaluation = 150 original + 180 new cases = 330 cases, about 0.5 h.

### Must have
| # | run | detail | GPU h |
|---|---|---|---|
| 1 | finish RL pilot | running | 1.5 |
| 2 | SFT full | 4373 examples x 1 epoch, 3 seeds (2.8 h each) | 8.4 |
| 3 | SFT data curve | 500 and 1000 examples, 1 seed (2000 exists) | 1.0 |
| 4 | RL main | 150 steps from each SFT seed (about 3.8 h each) | 11.4 |
| 5 | RL ablation | no match term, 150 steps, seed 0 | 3.8 |
| 6 | one-shot evaluation | base, 3 curve points, SFT x3, RL x3, ablation: 11 models x 0.5 h | 5.5 |
| 7 | repair loop | base, SFT, RL (seed 0): about 3 x one-shot at most | 4.0 |
| | **total** | | **35.6** |

### Only if ahead of schedule (in this order)
| # | run | GPU h |
|---|---|---|
| 8 | base with 3 worked examples per level (stronger prompting baseline; check length fits) | 0.7 |
| 9 | Qwen3.5-4B base, one shot (4-bit or bf16: state which) | 1.5 |
| 10 | 4B SFT, 2000 examples, 4-bit (about 6.3 s per step) plus evaluation | 5.0 |
| 11 | second RL ablation: no advantage normalisation or one update per batch | 3.8 |

Available: about 66 h of wall clock from Thu 16:30 to Sun 12:00. Must-have 34 h after the pilot leaves about 30 h of slack for stalls,
reruns and items 8-11. Long runs go overnight.

## 5. Schedule
| when | GPU | people |
|---|---|---|
| Thu to 16:30 | RL pilot + evaluation | fix venue; start writing new test prompts |
| Thu 16:30-18:30 | SFT 500, 1000 + evaluations | decide RL variant; Claude: repair loop code, multi-seed run script, smoke tests |
| Thu night | SFT full x3 (8.4 h), then SFT evaluations | **new prompts frozen before 08:00 Fri, before any evaluation on them** |
| Fri day, night | RL x3 (11.4 h), RL ablation (3.8 h) | dataset hand check |
| Sat | evaluations, repair loop, optional 8-10 | hand judging of outputs |
| Sun to 12:00 | reruns only | tables, agreement, intervals |

Cut order if late: item 5, then RL seeds 3 and 2 (report 1 seed and say so), then item 3. Never cut the held-out test set or the hand check.

## 6. Held-out test set (needed from the user)
* 2 maps not used anywhere (not train, val, Paris centre, Munich); 30 prompts per map, 60 total, 180 cases over three levels.
* Written by a person who has not looked at `training/sampler.py` templates (best: a colleague). Claude does not write them: it wrote the training templates.
* For each prompt note the required properties (same `expect` format as `eval/prompts_munich.json`) before seeing any output.
* Frozen and hashed before the first evaluation on it. No changes to prompts, checks or protocol afterwards; disclose any that happen.

## 7. Gates
* After item 1 (Thu 16:30): RL continues only if the reward on training replies rose and validation acceptance did not fall.
  If it shows no gain, decide: change the variant once, or report RL as a null result with 1 seed and spend the hours on items 8-10.
* After item 2: if full-data SFT does not beat the 2000-example pilot, use 2000 for RL.
* Each long run starts only after a short smoke test, and with the user's go-ahead.

## 8. Decisions open tonight
1. RL variant. Pilot: group-normalised advantage, clipped ratio, **one update per batch**, so the clip never acts. Proposal: two updates per batch
   without dividing by the group standard deviation (verify the Dr. GRPO definition in its paper first). Needs a smoke test.
2. Who writes the held-out prompts and which two maps.
3. Whether a second annotator is available.

Pilot result (26 Nov, 16:00): SFT vs SFT+RL accepted 98 vs 96 of 150 (50 prompts) and 95 vs 97 of 116 (validation); no significant difference.
Decided (user): the next RL run trains on **hard examples only**: new prompts on training maps, each sampled several times with SFT, kept when
the mean reward is below a threshold (set after looking at the distribution). Test and validation sets are never filtered.

Decided (user, 26 Nov, evening); these override sections 1-5 where they differ:
* **Drop L2** from the final study. Levels: L0 (code) and L1 (specification), one model trained on both. L2 only combines and names given
  library formulas (it cannot create new primitives), and its training definitions were mostly renamings.
* **No agentic condition** for the trained models. Columns: single pass; resampling on rejection and few-shot to be settled with the final models.
* The earlier schedule is dropped: first show on the pilot whether RL improves on SFT.
* The running hard-example pilot still contains L2 prompts, like the first pilot, so the two stay comparable.

## 9. Hand verification (no GPU)
| task | items | time | rule |
|---|---|---|---|
| dataset sample, stratified by kind and level | 300 | 3-4 h | correct / wrong + reason; report error rate with interval; do not call the dataset human-verified |
| outputs: base, SFT, RL (seed 0) on the held-out set; judge accepted replies only (rejected count as failures) | about 350 | 5-6 h | model hidden, order shuffled; does the scenario do what the request says (yes / partly / no) |
| second annotator, subset of both | 100 | 2 h | report agreement (Cohen's kappa) |

Tools to build: a sheet or player link per item with the request, blinded id and answer columns.

## 10. Metrics and statistics
Accepted, matching (automatic), human-judged match, replies needed (repair), per level and per type. Mean over training seeds with the range;
Wilson intervals per run; paired sign tests on the same cases between conditions.

## 11. Disclosures
Original prompts used in development; synthetic training data that passes the evaluation checks; templates written knowing the original prompts
(near-duplicates filtered); one-shot prompt fixed after a smoke test; default-script rule added after seeing base results; reward uses a verified
target as well as checks; automatic matching is lenient (an accepted "walk, cross, continue" reply with no crossing action counted as matching);
SFT pilot resumed once without optimizer state (pilot only).

## 12. Release
Dataset (training, validation, held-out prompts), splits by map, generator, checks, adapters, raw evaluation records, hand judgements, datasheet.
Map-derived files carry OpenStreetMap attribution (ODbL). Check the licence of Qwen3.5-2B before releasing adapters. Add a LICENSE file (none yet).
