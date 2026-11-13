cd /c/urbanscenariogenerator/usg
P=.usg_env/Scripts/python.exe
ONLY=$(cat only_v6.txt)
for m in munich paris_center; do for l in 2 1 0; do
$P scripts/benchmark.py --prompts eval/prompts_$m.json --out paper/results/final_${m}_l$l.jsonl --levels $l --reps 2 --ctx 24576 --assist world --save-specs --only $ONLY >> paper/results/final_${m}_l$l.log 2>&1
done; done
touch paper/results/V6_DONE
