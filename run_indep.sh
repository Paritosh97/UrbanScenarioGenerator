cd /c/urbanscenariogenerator/usg
for m in sophia:sa grenoble:grenoble paris_center:paris_center; do
  f=${m%%:*}; p=${m##*:}
  .usg_env/Scripts/python.exe scripts/benchmark.py --prompts eval/prompts_$f.json --out paper/results/${f}_indepfix.jsonl --levels 1 2 --reps 3 --ctx 24576 --save-specs --only ${p}_indep_comp_1 ${p}_indep_comp_2 ${p}_indep_comp_3 > paper/results/${f}_indepfix.log 2>&1
done
