# Evaluation plan (five areas, several model sizes, human rating)

What has been run and what is left. Commands are resumable (results are appended to JSONL).

## Design

| factor | levels |
|---|---|
| **areas** | Sophia Antipolis / Biot (done), Paris city centre, Paris-Saclay, Grenoble centre, Munich old town; plus the synthetic city for development and tests |
| **pipelines** | keyword baseline (no model), L0 (script), L1 (specification), L2 (specification + own definitions) |
| **models** | *open, local*: models of at most 4B parameters, several sizes (LM Studio names, e.g. `0.6B 1.7B 4B`); *open, larger*: any model behind a vLLM / Ollama OpenAI-compatible endpoint; *closed*: Claude and Gemini through their OpenAI-compatible endpoints (`--base-url`, `--remote-models`, key in an environment variable); temperature 0.2; 3 repetitions |
| **modularity (RQ3)** | **T0** bare prompt template (one call with the same context as L0, no tools, no repair; what a user gets by pasting the template into a chat model), **L0** script + helpers, **L1** specification, **L2** specification + own definitions, each with or without the **VLM** map image (`--vision`; needs a vision-capable model and, locally, its `mmproj`) |
| **prompts** | the Sophia set (25 prompts: 7 types x 3 phrasings + 4 mixed), filtered per map by `scripts/make_prompts.py` so that no prompt asks for an object the map lacks |
| **metrics** | valid, first try (no repair), adherence, axes recall, nominal-walker margin, steps, time; **human rating** of prompt-scenario match (0-1, Text2Scenario protocol); statistics: Wilson 95% intervals, exact sign tests on paired runs |
| **environment** | scripted / straight / random policies in the headless environment (`docs/TRAINING.md`) on the generated dataset |

**Keep development and test apart.** The system was tuned on the Sophia prompts (four pilot runs, disclosed in `paper/METHOD.md` section 9). Treat the
synthetic city and Sophia as *development* data. Freeze the code (tag a commit), then run the other four areas once, and report them as the held-out test.
Do not change prompts or code between seeing a failure on a new area and reporting it; list such failures instead.

## Step by step

```bash
cd usg
# 1. maps (needs network access to overpass-api.de; commit the files so the dates are fixed)
python scripts/fetch_maps.py                       # paris_center paris_saclay grenoble munich (sophia is cached)
for m in paris_center paris_saclay grenoble munich; do python scripts/make_prompts.py $m; done

# 2. freeze: git tag eval-v1

# 3. generation benchmark, one run per area and model set (hours on an integrated GPU; ~184 min for 75 L2 runs of the 4B model)
python scripts/benchmark.py --prompts eval/prompts_paris_center.json --levels 0 1 2 --reps 3 --models 0.6B 1.7B 4B \
       --save-specs --out ../paper/results/benchmark_paris_center.jsonl
#    ... same for the other areas; --no-llm gives only the keyword baseline
python scripts/summarize_benchmark.py ../paper/results/benchmark_paris_center.jsonl ../paper/results/paris_center

# 4. dataset + environment baselines
python scripts/make_dataset.py --out dataset --variants 4 --test-maps munich grenoble --runs ../paper/results/benchmark_paris_center.jsonl
python scripts/eval_baselines.py --dataset dataset --out ../paper/results/env_baselines.md

# 4b. open vs closed models and the bare template (hosted models: no GPU needed; costs API credit)
export API_KEY=...                                    # the key of the provider
python scripts/benchmark.py --prompts eval/prompts_sophia.json --levels 0 1 2 --template --reps 3 --save-specs \
       --base-url <openai-compatible endpoint of the provider> --remote-models <model name> --out ../paper/results/benchmark_api.jsonl
#    the same call with --vision for the map-image ablation (the model must accept images)

# 5. human rating (Text2Scenario protocol), after ethics clearance
python scripts/rating.py sheet --runs ../paper/results/benchmark_paris_center.jsonl --prompts eval/prompts_*.json --n 60 --raters 15 --out ../paper/rating
#    raters fill ../paper/rating/ratings.csv ; then
python scripts/rating.py summary --dir ../paper/rating
```

`summarize_benchmark.py` adds a table per map and per model when the JSONL contains several. Pairwise pipeline tests are computed for the first model;
filter the JSONL by `model` for the others.

## Valid output by construction, and tiers
A generated scenario should always be valid and load in a standard player. Two options of `benchmark.py` make that a property of the pipeline instead of luck:
* `--esmini <bin folder>` (or `ESMINI_BIN`): a scenario is accepted only if esmini loads and runs it; a failure goes back to the model as a validator error.
* `--assist world|fallback`: deterministic safety nets (`usg/assist.py`). `world` writes the world script from an accepted specification; `fallback` also submits the reference script of the likely
  type when the model produced nothing usable.

Every record has a `tier` (`model` | `assisted` | `fallback`). **Report them separately:** `accepted` is what the model achieved alone, `valid_output` (any tier) is what the pipeline guarantees.
A `fallback` scenario is valid but need not match the request, so its adherence is usually false. The summary tables show both columns. `scripts/replay_failures.py` replays recorded failures
through the nets offline (`paper/results/replay_failures.md`).

## Status

| item | status |
|---|---|
| L2 on Sophia, 4B, 75 runs | done (`paper/results/sophia_l2.jsonl`) |
| keyword baseline, 32 prompts (synthetic city + Munich) | done |
| headless environment, reference policies, dataset builder, rating tools, multi-map / multi-model benchmark options | implemented and tested (`tests/test_env.py`, `tests/test_dataset.py`) |
| environment baselines on Sophia + synthetic city | `paper/results/env_baselines_demo.md` and `dataset_stats_demo.md` (two areas only; rerun on all five). Findings: the seven reference scripts are easy (straight 98%, route 96%, random 17%); with the traffic-light scenarios straight drops to 75% (0% on them), route 97%, random 12% |
| esmini compatibility check (`scripts/check_standards.py`, esmini v3.10.2) | 69/69 generated scenarios load and run after the signal export was made standard-conform (the first run: 53/69, the 16 with traffic lights were rejected): `paper/results/standards_check.md`. OpenDRIVE: 824/824 roads load, 98% of 1344 centre-line samples within 0.5 m |
| OSM extracts for Paris x2, Grenoble, Munich | **not downloaded** (the build environment blocked overpass-api.de): run `scripts/fetch_maps.py` |
| prompt sets for the four areas | generated by `scripts/make_prompts.py` once the extracts exist |
| generation benchmark on the four areas, several model sizes | **not run** (needs LM Studio models and hours of GPU time) |
| L0 / L1 / L2 modularity, T0 bare template, vision (VLM) ablation, open vs closed models | harness implemented and tested (`tests/test_benchmark.py`); **not run** (needs models / API keys; commands above) |
| human rating study, pilot with participants | **not run** (needs participants and, probably, ethics approval) |
| learned agent in the environment | not planned for this paper (scripted baselines only) |

## Threats to validity (state them)

Prompts are written by the author; request checks are keyword based; the nominal walker is an idealised participant; other road users are
scripted; OSM quality differs by city and changes over time (record the download date); models of at most 4B follow nuanced prompts only partly;
the system was tuned on one area.
