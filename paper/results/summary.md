# Benchmark results

37 runs; model: Qwen3.5-4B Q4_K_M (LM Studio llama.cpp, Vulkan, AMD iGPU), temperature 0.2.


## All prompts

| pipeline | runs | valid (accepted) | first try (no repair) | adherent | axes recall | nominal walker ok | mean steps | mean s |
|---|---|---|---|---|---|---|---|---|
| keyword baseline (no model) | 32 | 100% [89, 100] | 100% [89, 100] | 59% [42, 74] | 0.71 | 97% [84, 99] | 0.0 | 2 |
| L0 script + task helpers | 2 | 100% [34, 100] | 100% [34, 100] | 100% [34, 100] | 1.00 | 100% [34, 100] | 1.0 | 32 |
| L1 specification (library) | 2 | 50% [9, 91] | 50% [9, 91] | 50% [9, 91] | 0.50 | 100% [21, 100] | 6.5 | 92 |
| L2 specification + own definitions | 1 | 100% [21, 100] | 100% [21, 100] | 100% [21, 100] | 1.00 | 100% [21, 100] | 2.0 | 40 |

## mixed (several constraints, look/wait)

| pipeline | runs | valid (accepted) | first try (no repair) | adherent | axes recall | nominal walker ok | mean steps | mean s |
|---|---|---|---|---|---|---|---|---|
| keyword baseline (no model) | 4 | 100% [51, 100] | 100% [51, 100] | 0% [0, 49] | 0.67 | 100% [51, 100] | 0.0 | 2 |

## real map (Munich)

| pipeline | runs | valid (accepted) | first try (no repair) | adherent | axes recall | nominal walker ok | mean steps | mean s |
|---|---|---|---|---|---|---|---|---|
| keyword baseline (no model) | 7 | 100% [65, 100] | 100% [65, 100] | 71% [36, 92] | 0.86 | 86% [49, 97] | 0.0 | 2 |

## the 7 named types (synthetic city)

| pipeline | runs | valid (accepted) | first try (no repair) | adherent | axes recall | nominal walker ok | mean steps | mean s |
|---|---|---|---|---|---|---|---|---|
| keyword baseline (no model) | 21 | 100% [85, 100] | 100% [85, 100] | 67% [45, 83] | 0.67 | 100% [85, 100] | 0.0 | 2 |
| L0 script + task helpers | 2 | 100% [34, 100] | 100% [34, 100] | 100% [34, 100] | 1.00 | 100% [34, 100] | 1.0 | 32 |
| L1 specification (library) | 2 | 50% [9, 91] | 50% [9, 91] | 50% [9, 91] | 0.50 | 100% [21, 100] | 6.5 | 92 |
| L2 specification + own definitions | 1 | 100% [21, 100] | 100% [21, 100] | 100% [21, 100] | 1.00 | 100% [21, 100] | 2.0 | 40 |

## Adherence per scenario type (all pipelines with a model)

| type | keyword baseline (no model) | L0 script + task helpers | L1 specification (library) | L2 specification + own definitions |
|---|---|---|---|---|
| cpath | 75% [30, 95] | - | - | - |
| dep_comp | 25% [5, 70] | - | - | - |
| dyn_nav | 100% [51, 100] | - | - | - |
| env_con | 75% [30, 95] | - | - | - |
| indep_comp | 50% [15, 85] | - | - | - |
| mixed | 0% [0, 43] | - | - | - |
| ptp_env | 100% [51, 100] | 100% [34, 100] | 50% [9, 91] | 100% [21, 100] |
| ptp_road | 67% [21, 94] | - | - | - |

## Paired comparisons (same prompt and repetition)

| comparison | metric | A only | B only | both | neither | sign-test p |
|---|---|---|---|---|---|---|
| A=L0 text, B=L1 | accepted | 1 | 0 | 1 | 0 | 1.000 |
| A=L0 text, B=L1 | first_try | 1 | 0 | 1 | 0 | 1.000 |
| A=L0 text, B=L1 | adherent | 1 | 0 | 1 | 0 | 1.000 |
| A=L0 text, B=L2 | accepted | 0 | 0 | 1 | 0 | 1.000 |
| A=L0 text, B=L2 | first_try | 0 | 0 | 1 | 0 | 1.000 |
| A=L0 text, B=L2 | adherent | 0 | 0 | 1 | 0 | 1.000 |
| A=L1 text, B=L2 | accepted | 0 | 0 | 1 | 0 | 1.000 |
| A=L1 text, B=L2 | first_try | 0 | 0 | 1 | 0 | 1.000 |
| A=L1 text, B=L2 | adherent | 0 | 0 | 1 | 0 | 1.000 |

## What the generated specifications contain

Operators used in accepted L1/L2 scenarios: in_zone (2)

L2 scenarios that defined their own definitions: 0 of 1 accepted.

## Why runs failed

**L1 specification (library)**: too many rejected scripts ×1

Most frequent rejection feedback, L1 specification (library):
- ×4 submit_script:  ERROR
