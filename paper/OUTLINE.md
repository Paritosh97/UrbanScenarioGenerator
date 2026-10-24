# Paper outline (target: Computers & Graphics)

Working title: *A human-in-the-loop framework for creating and testing user-guided pedestrian scenarios and tasks from text and maps*

**Idea in one paragraph.** From a text prompt and an OpenStreetMap area the framework generates a *scenario* (road users, signals) and *guided tasks* for one ego
user ("wait for green, look at the car, then cross"). The tasks are written in a small typed language of temporal formulas, carried by an extension of the existing AV
standards (OpenSCENARIO / OpenDRIVE), validated against the map, and run live in a VR / first-person player that monitors the formulas. The ego can be a **human**
(VR or first person) or a **synthetic user agent** built from classical algorithms (route planning on the pedestrian graph, path following, waiting at red lights,
yielding); the synthetic agent also proves that a generated scene is doable. No learning is involved in the agent. Learned agents are future work.

**Abstract.** Problem, approach, evaluation (modularity L0/L1/L2 and VLM, open and closed models, five real areas, human rating), results, release.

## 1. Introduction
1.1 Motivation: user studies in VR / first person (e.g. low-vision and rehabilitation research) and human-in-the-loop testing need guided tasks in realistic traffic; authoring them by hand is slow and not reproducible.
1.2 Problem: no tool generates guided tasks for a human pedestrian from a real map and a prompt, validates them, and exports a standard format that existing tools can load.
1.3 Research questions
* **RQ1 standards and expressiveness.** Can existing AV scenario standards (OpenSCENARIO, OpenDRIVE) be extended to express user-guided pedestrian tasks, with files that standard tooling still loads? Which task types and constraints does the extension capture?
* **RQ2 generation.** Can a grounded LLM agent with a constrained DSL generate valid, executable scenarios from a prompt and an OSM area, across areas and across open and closed models?
* **RQ3 modularity.** What does each module contribute to validity and faithfulness: the bare prompt template (T0), the script pipeline (L0), the formal specification (L1), model-defined definitions (L2), the validator / repair loop, and a VLM map image?
* **RQ4 usability.** Are the generated scenarios usable as tasks (a) for human participants (playable, completable, relevant) and (b) for synthetic user agents (solvable, and scores that separate agents)? What kinds of use does that open (see 1.5)?

1.4 Contributions (what this paper claims)
1. An extension of OpenSCENARIO / OpenDRIVE with a typed task specification language that has quantitative (margin) semantics, one evaluation path in Python and in the player (parity tested).
2. A modular, map-grounded generation pipeline (T0 / L0 / L1 / L2, optional VLM input) with a validator and a repair loop.
3. A human-in-the-loop execution and validation framework: VR / first-person player with a live monitor, and a classical synthetic user agent that checks doability.
4. An evaluation across five real areas, open and closed models, the modular conditions, and a human rating of prompt-scenario match.

1.5 Enabling artifacts, applications and future work (stated, **not** claimed as contributions)
* *Released interfaces:* headless environment (reset / step, reward from the same monitor, safety cost), dataset with splits by map, reference policies. Lightly evaluated.
* *Applications that motivate the work:* VR user studies, rehabilitation and low-vision research; human pedestrians in AV / ADAS interaction testing; benchmarks for rule-constrained navigation of robots, delivery vehicles and wheelchairs (measurable compliance with formal rules).
* *Future work:* reinforcement or imitation learning on the environment; synthetic users learned from data; learned generators; reactive traffic; eye tracking.

1.6 Outline of the paper.

## 2. Related work
2.1 Pedestrians in the loop and VR experiments (GUsT-3D, JaywalkerVR, Robert et al.)
2.2 Scenario languages and standards (OpenSCENARIO, OpenDRIVE, Scenic, GeoScenario)
2.3 LLM-based scenario generation (ChatScene, ScenicNL, Text2Scenario, Txt2Sce, LLM4AV)
2.4 Pedestrian scenario generation for AV testing
2.5 Urban and 3D scene generation from maps
2.6 Environments and benchmarks for pedestrian / embodied navigation (MetaUrban and others)
2.7 Gap and positioning. **Comparison with prior systems is by expressiveness (a matrix of which task types and constraint axes each system can express), not head to head:** the closest systems generate vehicle-under-test scenarios and cannot express a pedestrian ego with formal goal and safety rules. Never write "first".

## 3. Task model and specification language (RQ1)
3.1 Guided tasks = reach a target + constraints. 3.2 Taxonomy as constraint axes (7 types). 3.3 Entity types, atoms, combinators. 3.4 Standard library and model-defined definitions (L2). 3.5 Quantitative semantics on trajectory prefixes. 3.6 Encoding in OpenSCENARIO 1.3 (`<VRTask>` / `<Spec>`) and OpenDRIVE; loading in standard tools. 3.7 Coverage analysis against prior task sets.

## 4. Framework (RQ2, RQ3, RQ4)
4.1 One frame, one map (OSM to metric model, scene map, OpenDRIVE). 4.2 Generation pipeline and its modules: T0, L0, L1, L2, VLM map image. 4.3 Agent loop: pre-fetched context, grounded tools, text tool format, repair from validator messages. 4.4 Validation: document check, sandboxed script, rules derived from the formulas. 4.5 The synthetic user agent (route planning, path following, waiting, yielding) as a doability check. 4.6 The player: live monitor, inspector, result export. 4.7 Interfaces for downstream use (environment, dataset) in brief.

## 5. Evaluation
5.1 Setup: five areas + synthetic city (development vs held-out areas), prompt sets, repetitions. Models: open local (at most 4B, several sizes), open larger via endpoint, closed (Claude, Gemini) through the same agent.
5.2 Metrics: validity, first-try validity, adherence, axes recall, nominal-walker margin, steps and time; human rating of prompt-scenario match (Text2Scenario protocol, ICC).
5.3 Results
* RQ2: by area, by model (open vs closed, size).
* RQ3: T0 vs L0 (value of tools and repair), L0 vs L1 vs L2 (value of the formal specification and own definitions), with and without the VLM image; human ratings.
* Failure analysis.
5.4 RQ4(b): synthetic agents in the headless environment: the classical agent solves the generated scenarios; random and map-blind agents do not (demo on two areas: random 17%, straight 98%, scripted 96% on the easy reference scenarios; the harder L1/L2 scenarios are needed to separate map-aware from map-blind behaviour).
5.5 RQ4(a): pilot with participants (few participants, outcome logs, short questionnaire, qualitative).
5.6 Threats to validity.

## 6. Discussion. What the formal specification buys; what model size and open vs closed change; what the synthetic agent does and does not prove; the applications of 1.5.
## 7. Limitations and future work. Keyword request checks; scripted (non-reactive) traffic; placeholder props; OpenDRIVE not validated against esmini; no eye tracking; no object interaction; no learned agents.
## 8. Conclusion

Declarations: acknowledgements, CRediT, ethics / consent (rater study, pilot), data and code availability. Appendices: A prompts per area; B DSL grammar and atoms; C example files; D environment schema; E extra results.

## Status (commands in `docs/EVALUATION.md`)

| area | done | open |
|---|---|---|
| specification language, monitor (Python + TypeScript), parity tests | yes | |
| generation pipeline L0 / L1 / L2, validator, synthetic user agent, player | yes | headset sessions untested |
| harness for T0, remote open / closed models, VLM image, several local sizes, per-map / per-model tables | implemented, tested without a model | run it (models, API keys, GPU hours) |
| headless environment, reference policies, dataset builder, rating tools | yes (tests) | harder L1/L2 scenarios in the dataset |
| main result: L2 on Sophia, 4B | yes (75 runs, 39 accepted) | |
| four more areas (Paris centre, Paris-Saclay, Grenoble, Munich) | fetch and prompt scripts ready | download the extracts (blocked in the build environment), generate prompts, run |
| RQ1 evidence | extension implemented | test loading in esmini / XSD validation; coverage analysis (read GUsT-3D, JaywalkerVR, CREATTIVE3D) |
| human rating, pilot (RQ4a) | rating tooling ready | ethics, raters, participants |
| novelty check | 4 web searches | systematic search; read LLM4AV and Text2Scenario in full; expressiveness matrix |
| bibliography, template | | Zotero export, Computers & Graphics template |
| admin | | ethics requirement, contract IP / publication clause |
