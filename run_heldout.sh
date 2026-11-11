cd /c/urbanscenariogenerator/usg
while ! grep -q "finished in" paper/results/sophia_abl.log 2>/dev/null; do sleep 30; done
for m in grenoble paris_center; do
  .usg_env/Scripts/python.exe scripts/benchmark.py --prompts eval/prompts_$m.json --out paper/results/${m}_l2.jsonl --levels 2 --reps 3 --ctx 24576 --save-specs > paper/results/${m}_l2.log 2>&1
done
