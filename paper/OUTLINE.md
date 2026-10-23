# Paper outline (target: Computers & Graphics)

Working title: *Generating map-grounded guided pedestrian tasks for VR from text, with a formal task specification and a training-ready benchmark*

**Abstract.** Problem, approach, evaluation (five real areas, models of at most 4B, L0/L1/L2, human rating), main results, open-source release.

## 1. Introduction
1.1 Motivation: VR and first-person studies of pedestrians in traffic; hand authoring of scenarios is slow and not reproducible.
1.2 Problem: no tool generates guided tasks for a **human pedestrian** from a real map and a text prompt, validated and in a standard format.
1.3 Research questions
* **RQ1 representation**: can a task taxonomy and a specification language capture guided pedestrian tasks and stay compatible with OpenSCENARIO / OpenDRIVE?
* **RQ2 generation**: can a grounded LLM agent with a constrained DSL produce executable scenarios from a prompt and an OSM area? How does this vary by area and by model size (at most 4B)?
* **RQ3 validity and faithfulness**: do map-aware validation and a repair loop make scenarios valid and faithful to the prompt, judged automatically and by human raters?
* **RQ4 utility**: (a) are the scenarios usable as training and benchmark tasks (dense reward, solvable, diverse)? (b) are they playable and seen as relevant by pilot users? (b) is qualitative and exploratory.

1.4 Contributions
1. A typed task specification language with quantitative (margin) semantics, one evaluation path in Python and in the VR player (parity tested).
2. A two-stage, map-grounded agent pipeline (specification, then world script) with a validator, a repair loop and a nominal-walker feasibility check.
3. A standards-based encoding (OpenSCENARIO 1.3 and OpenDRIVE with a `<VRTask>`/`<Spec>` extension) and a WebXR / first-person player that monitors the formulas live.
4. A benchmark over five real areas and several model sizes with ablations and a human rating study.
5. A training-ready release: headless Gymnasium-style environment with a dense reward from the same monitor, a dataset with held-out-map splits, reference policies, open-source code.

1.5 Outline of the paper.

## 2. Related work
2.1 Pedestrians in the loop and VR experiments (GUsT-3D, JaywalkerVR, Robert et al.)
2.2 Scenario languages and standards (OpenSCENARIO, OpenDRIVE, Scenic, GeoScenario)
2.3 LLM-based scenario generation (ChatScene, ScenicNL, Text2Scenario, Txt2Sce, LLM4AV)
2.4 Pedestrian scenario generation for AV testing
2.5 Urban and 3D scene generation from maps
2.6 Simulation environments and benchmarks for pedestrian / embodied agents (MetaUrban and others)
2.7 Gap and positioning (safe wording, never "first").

## 3. Task model and specification language (RQ1)
3.1 Guided tasks = reach a target + constraints. 3.2 Taxonomy as constraint axes (7 types). 3.3 Entity types, atoms, combinators.
3.4 Standard library and model-defined definitions (L2). 3.5 Quantitative semantics on trajectory prefixes. 3.6 Coverage analysis against prior task sets.

## 4. System (RQ2, RQ3)
4.1 One frame, one map (OSM -> metric model, scene map, OpenDRIVE). 4.2 Pipeline levels L0, L1, L2. 4.3 Agent loop: pre-fetched context, grounded tools, text tool format.
4.4 Validation: document check, sandboxed script, rules derived from formulas, nominal walker. 4.5 Scenario encoding. 4.6 Player. 4.7 Headless environment and dataset (RQ4a).

## 5. Evaluation
5.1 Setup: five areas + synthetic city, prompt sets, models of at most 4B, pipelines, repetitions; development vs held-out areas.
5.2 Metrics: automatic (valid, first try, adherence, recall, nominal margin, cost) and human rating (Text2Scenario protocol, ICC).
5.3 Results: RQ2 by area and model size; RQ3 effect of the validator, repair loop and ratings; ablations (L0/L1/L2, optional vision); failure analysis.
5.4 Dataset and environment (RQ4a): coverage and diversity statistics; scripted / straight / random policies by split; reward-signal check.
5.5 Pilot study (RQ4b): few participants, outcome logs, short questionnaire.
5.6 Threats to validity.

## 6. Discussion. What the specification language buys; what model size changes; where the system fails; what the reward does and does not measure.
## 7. Limitations and future work. Keyword request checks, no eye tracking, scripted (non-reactive) traffic, placeholder props, OpenDRIVE not validated against esmini, no object interaction, no learned agents yet.
## 8. Conclusion

Declarations: acknowledgements, CRediT contributions, ethics / consent (rater study and pilot), data and code availability.
Appendices: A prompts per area; B DSL grammar and atom catalogue; C example scenario files; D environment schema; E extra results.

## What is done and what is open (see `docs/EVALUATION.md` for commands)

| area | done | open |
|---|---|---|
| specification language, monitor (Python and TypeScript), parity tests | yes | |
| agent pipeline, validator, nominal walker, player | yes | headset sessions untested |
| headless environment, reference policies, dataset builder, rating tools | yes (tests) | reward-signal study with a learned agent is out of scope |
| main result: L2 on Sophia, 4B | yes (75 runs) | |
| four more areas (Paris centre, Paris-Saclay, Grenoble, Munich) | scripts and prompt generator ready | download the OSM extracts (blocked in the build environment), generate prompts, run |
| several model sizes (at most 4B) | `--models` option ready | run |
| L0 / L1 / L2 and vision ablations | commands ready | run (optional) |
| human rating | tooling ready | ethics clearance, raters, scenarios as video or played |
| pilot with participants (RQ4b) | | everything |
| RQ1 coverage analysis | | read GUsT-3D, JaywalkerVR, CREATTIVE3D task sets in full |
| novelty check | 4 web searches | systematic search, read LLM4AV and Text2Scenario in full, citation chasing |
| bibliography, venue formatting | | re-export from Zotero, Computers & Graphics template |
| admin | | ethics requirement, contract IP / publication clause |
