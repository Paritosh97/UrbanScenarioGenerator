#!/usr/bin/env bash
# Waits for the main benchmark to finish, then runs the vision ablation (L2 with an annotated map image) and the summary.
# Usage (from usg/):  bash scripts/after_main_benchmark.sh
cd "$(dirname "$0")/.."
LOG=../paper/results/benchmark.log
until grep -q "finished in" "$LOG" 2>/dev/null; do sleep 60; done
echo "main benchmark finished: $(date)"
./.usg_env/Scripts/python.exe -u scripts/benchmark.py --vision --levels 2 --reps 2 --out ../paper/results/benchmark.jsonl > ../paper/results/benchmark_vision.log 2>&1
echo "vision ablation finished: $(date)"
./.usg_env/Scripts/python.exe scripts/summarize_benchmark.py ../paper/results/benchmark.jsonl ../paper/results > ../paper/results/summarize.log 2>&1
echo "summary written: $(date)"
