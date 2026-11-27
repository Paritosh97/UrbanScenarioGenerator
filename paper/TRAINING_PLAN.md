# Study plan: SFT + hard-example RL for text-to-scenario (planning notes, not paper text)

Updated 26 Nov 2026, evening. Replaces the earlier versions of this file (copy in `paper/slides/bak/docs_26nov`). Implementation detail and pilot numbers: `METHOD.md` Part 0.

## 1. Method
1. Generate a large set of scenarios procedurally; keep only those that pass every check (each request then has a verified reference scenario).
2. SFT on part A.
3. The SFT model answers part B (never used in SFT) several times per request.
4. Requests with a low mean reward (hard examples) form the RL set; RL starts from the SFT adapter.
5. Evaluate base, SFT and SFT+RL on test requests used in none of these steps. One final model answers every request; the threshold only selects training data.

## 2. Decisions
| topic | decision |
|---|---|
| models | Qwen3.5-2B: base, SFT, SFT+RL. 4B agent results kept as a reference study |
| levels | L0 (code) and L1 (specification); **L2 dropped**; one model trained on both |
| RL data | hard examples only |
| inference | single pass; resampling on rejection and/or few-shot to be settled with the final models |
| agentic | **not included** (the models are not trained on correction data; would need an untested model conversion) |
| human study | none; dataset and outputs checked by hand |
| schedule | the 3-day schedule is dropped; first show on the pilot whether RL improves on SFT |

## 3. Evaluation grid
| experiment | models | inference | levels |
|---|---|---|---|
| main | base, SFT, SFT+RL | single pass | L0, L1 |
| inference aids | base, SFT, SFT+RL | resampling (at most 3 attempts), few-shot (to decide) | main level (chosen on validation) or both |
| data size | SFT at several sizes | single pass | L0, L1 |
| RL ablation (only if RL helps) | without the match term; random instead of hard prompts (pilot 1 shows the idea) | single pass | L0, L1 |

## 4. Pilot status
| run | state | result |
|---|---|---|
| base and SFT (2000 examples), single pass | done | SFT far above base |
| RL 1: random SFT prompts, 50 steps | done | no significant difference from SFT (98 vs 96 of 150; 95 vs 97 of 116) |
| RL 2: hard examples only, 50 steps, evaluation with 3 samples per case | running (started about 16:10, 26 Nov) | pending |

RL 2 still contains L2 prompts so it stays comparable with RL 1. Report L0 and L1 separately.

Decision rule after RL 2: if SFT+RL is better on validation (paired, 3 samples), plan the final runs with hard-example RL. If not, inspect the hard pool
(how many prompts have differing rewards) and the reward curve; at most one further change (e.g. several updates per batch); otherwise report RL as a null result.
Never tune on the test prompts.

## 5. Still to plan (in this order)
1. **Generator for the final data:** sizes of parts A and B; more varied wording (the pilot has 1825 distinct request texts in 4373 examples; paraphrases, disclose how);
   no L2; more maps (add non-European areas); held-out constraint combinations for the "unusual combination" comparison of L0 and L1.
2. **Held-out test set:** 2 or more unseen maps; requests written by people who have not seen the templates (not by Claude, which wrote them); required properties
   noted before seeing outputs; frozen and hashed before first use.
3. **RL variant:** several updates per batch, Dr. GRPO-style advantage, group size, steps.
4. Seeds (at least 3 for the main comparison) and GPU budget.
5. Inference-aid columns.

## 6. Compute (measured, RTX 4060 Ti 16 GB)
SFT 2.3 s per example (4373 examples: 2.8 h); evaluation 4-6 s per case; RL 75-110 s per step (4 x 4); hard-example scoring about 75 s per 8 prompts x 3 samples;
data generation about 85 examples per minute (CPU, 3 workers). Without the memory cap a run pages into system RAM and stalls. Ask before long GPU runs.

## 7. Hand verification (no GPU)
| task | items (adjust to final sizes) | rule |
|---|---|---|
| dataset sample, stratified by kind and level | about 300 | correct / wrong + reason; report the error rate with interval; never call the set human-verified |
| model outputs on the held-out set, accepted replies only (rejected count as failures) | about 350 | model hidden, order shuffled; does it do what was asked (yes / partly / no) |
| second annotator, subset | about 100 | report agreement (Cohen's kappa) |

Tool still to build: blinded sheet with request, player link and answer columns.

## 8. Metrics and statistics
Accepted, automatic match, hand-judged match, per level and type. Mean over seeds with range; Wilson intervals; paired sign tests on the same cases.

## 9. Disclosures
Original 50 prompts used while developing the pipeline; synthetic training data that passes the same checks as evaluation; templates written knowing the original
prompts (near-duplicates filtered); single-pass prompt fixed after a smoke test; default-script rule added after seeing base results; the reward uses a verified
target as well as checks; automatic matching is lenient; pilot SFT resumed once without optimizer state; L2 dropped after the pilot (and why).

## 10. Release
Datasets and splits, generator, checks, adapters, raw evaluation records, hand judgements, datasheet. OpenStreetMap attribution (ODbL) for map-derived files.
Check the Qwen3.5-2B licence before releasing adapters. Add a LICENSE file (none yet).
