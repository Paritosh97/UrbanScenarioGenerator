file:///C:/urbanscenariogenerator/paper/ref_paper.pdf
https://www.youtube.com/watch?v=UY7sVKJPTMA
undertsand the method and check results
write the outline. the table figures in a logical sequence as if i am arranging them for a presentation. 
write the experiments and methods section
write the results section based on outline
cleanup and write conclusions in numbered format
do the ppt
write the introduction and abstract
produce references

explain L0 L1 and L2

method:
3.1 extended dsl for scenario generation for ego user
3.2 llm and agentic pipeline for scenario generaration

filter references


urban scneario generator:
- define a limit, a less ambitious one but define a limit

open items for the paper (see paper/OUTLINE.md and docs/EVALUATION.md):
- run scripts/fetch_maps.py (needs network), then scripts/make_prompts.py for paris_center paris_saclay grenoble munich; commit eval/maps/*.osm
- freeze the code (git tag), run scripts/benchmark.py on the four new areas with --models <sizes up to 4B> --save-specs
- build the dataset and the environment baselines on all five areas (scripts/make_dataset.py, scripts/eval_baselines.py)
- ethics check, then the human rating study (scripts/rating.py) and the pilot with participants
- RQ1 coverage analysis (read GUsT-3D, JaywalkerVR, CREATTIVE3D); systematic novelty search, read LLM4AV and Text2Scenario in full
- Computers & Graphics template, bibliography from Zotero

