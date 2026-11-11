cd /c/urbanscenariogenerator/usg
for job in munich:2 munich:1 paris_center:2 paris_center:1 munich:0 paris_center:0; do
  m=${job%%:*}; l=${job##*:}
  .usg_env/Scripts/python.exe scripts/benchmark.py --prompts eval/prompts_$m.json --out paper/results/final_${m}_l$l.jsonl --levels $l --reps 2 --ctx 24576 --assist world --save-specs > paper/results/final_${m}_l$l.log 2>&1
done
echo ALL_DONE > paper/results/final_done.flag
