# Evaluation (final setup)

Two real maps (Paris centre, Munich), 25 prompts each, Qwen3.5-4B Q4_K_M through LM Studio, temperature 0.2, context 24576, 2 repetitions, levels 0 / 1 / 2.
The final system (v6) is used for every run; the reported results are one run of v5 for all types, with the types dyn_nav, mixed, env_con and ptp_env re-run with v6 (two plumbing fixes: `when_task_starts(None)` reads as the first task; `Place` attribute hint), `run_v5.sh`, `run_v6.sh`, `only_v6.txt`; earlier runs are development records in `paper/results/old_v1` ... `old_v5`: deterministic repair on (`--assist world`, tier recorded per run), "any order" composition recognised in three equivalent forms,
world scripts that add tasks beyond the specification rejected. See `paper/METHOD.md` sections 8 and 9 for the metrics and the disclosures.

## Run (resumable; one JSONL per map and level)

```bash
cd usg
python scripts/fetch_maps.py paris_center munich            # OSM extracts into eval/maps/ (network; USG_OVERPASS=<url> selects another Overpass server)
python scripts/make_prompts.py paris_center                 # eval/prompts_<map>.json from the template eval/prompts_sophia.json
python scripts/make_prompts.py munich
for m in munich paris_center; do for l in 2 1 0; do
  python scripts/benchmark.py --prompts eval/prompts_$m.json --out paper/results/final_${m}_l$l.jsonl \
      --levels $l --reps 2 --ctx 24576 --assist world --save-specs
done; done
python scripts/final_tables.py                              # tables -> paper/results/*.tex and summary.md
```

`--assist world` records the tier of every run (`model` | `assisted`); `accepted` counts the model tier only, `valid_output` counts any tier. Rejected runs keep
`last_spec`, `last_code` and `last_feedback` (full rejection text) for the failure paragraph. Run time on an RTX 4060 Ti: the six jobs of the v5 run took about 3 h in total (25 to 40 minutes each, L0 included); the v6 re-run of four types took about 1 h; the first harness needed about 8 hours for all six jobs. A first full run (v1, before four harness fixes) is kept only as a development record; the pilot of the fixes is in `paper/results/pilot/`.

## Checks that do not need the model
```bash
python -m pytest -q                                          # unit tests (monitor parity, validator, builder, agent loop with a fake model)
python scripts/check_standards.py --esmini <esmini/bin>      # esmini loads and runs the files: 69/69 (see paper/results/standards_check.md)
```

## Human rating (RQ4)
```bash
python scripts/rating.py sheet --runs <accepted runs jsonl> --prompts eval/prompts_munich.json eval/prompts_paris_center.json --n 40 --raters 5 --out paper/rating
# raters fill paper/rating/ratings.csv (item_id, rater, score 0-1 in steps of 0.1); then
python scripts/rating.py summary --dir paper/rating
```
Items are shuffled and blinded (`key.csv` links them back). Raters should play or watch each scenario in the player, not only read the prompt.
