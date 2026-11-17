# Problem, research questions and state of the art

# FINAL SCOPE (12 Nov 2026) - supersedes every scope / evaluation note below (the literature notes A-H stay valid)

Angle: a framework for creating guided VR / first-person tasks for a human pedestrian from a real map and a prompt (target: Computers & Graphics).
Notes only, not paper text.

## Research questions and the evidence for each
| RQ | question | evidence |
|---|---|---|
| RQ1 | Can one small typed task language express guided pedestrian tasks and run them live for a human? | 7 task types as points on 6 axes; Python/TypeScript monitor parity tests; esmini 69/69 (`results/standards_check.md`); the player |
| RQ2 | Can a small local model (Qwen3.5-4B) generate valid scenarios from a prompt and a real map? | per-type table on Paris centre + Munich, L2, model-only and assisted tiers reported separately |
| RQ3 | What do the components contribute? | L0 / L1 / L2 on the same two maps; repair tier (assisted) vs model-only |
| RQ4 | Do people judge the scenarios as matching the prompt? | 5 raters, 40 blinded items (`paper/rating`) |

## Evaluation (one system version, one setup)
* Maps: Paris centre, Munich (OSM, fetched 10-12 Nov 2026). Prompts: 25 per map, identical templates (`eval/prompts_sophia.json` is the template; per-map files in `eval/`). Model: Qwen3.5-4B Q4_K_M, temperature 0.2, ctx 24576. 2 repetitions per prompt, levels 0, 1, 2.
* Final system: deterministic repair on (system builds the world if the model's script keeps failing; timeouts raised to the validator minimum), tier recorded per run; "any order" composition recognised in three equivalent forms; world scripts that add tasks beyond the specification are rejected; esmini gate off in the run (loading checked separately: 69/69).
* Nothing is claimed as held-out. State: the system and the prompts were developed iteratively on other maps (a Sophia Antipolis map with several pilot runs, then Grenoble); the same prompt templates were used on the evaluation maps.
* Reporting rules: k out of n in every cell with Wilson 95% intervals; model-only ("accepted") and assisted counts in separate columns, headline claims on model-only; no pooling across L0/L1/L2; per-type counts pooled over the two maps only (same system version).

## Contributions (what to claim)
1. A typed task specification language with signed margins; one monitor in Python and TypeScript (parity tested).
2. Map-grounded generation by a small local model with a validator and repair loop; deterministic repair reported as its own tier.
3. A player (WebXR / first person) that runs and monitors the same formulas live; export that standard tools load (esmini 69/69).
4. An evaluation: per-type results, L0/L1/L2, rater study.
Never write "first". Compare with prior work by expressiveness (matrix in NOTES), not head to head.

## Dropped from the paper (code may remain; mention only as future work or not at all)
Sophia and Grenoble results, the single-stage variant, vision ablation, keyword baseline, headless environment / dataset / reference policies, synthetic-agent evaluation, larger or closed models, the pilot with participants, the usgp idea (layout diffusion + 3D generation; folder `C:/urbanscenariogenerator/usgp`, one sentence in future work).

## Disclosures to write (threats to validity)
Prompts written by the author; one 4B model; 2 repetitions (wide intervals); adherence is axis-level only; nominal walker is idealised (1.2-1.3 m/s); repair, metric rule, duplicate-task check and four harness fixes (METHOD.md section 8) were designed from the failures of earlier runs; the reported numbers are one run of the final system; assisted scenarios are partly system-built.

## Yours to do
Rater study (5 raters), ethics statement, contract clause, read LLM4AV (Springer, paywalled) and Text2Scenario, fill the expressiveness matrix, write the paper, bibliography, Elsevier template.

---
(older notes below)

Source: the whole Zotero library (376 items; "Closest" subcollection marked ★) and the introduction/related work of `urbanscenariogenerator_osm/main.tex`.
Citations are given as Author Year (Zotero key). Items whose Zotero record has no year/venue are flagged "(year?)": check before citing.

## 1. Problem

Studying how people walk in cities (pedestrian safety, road-crossing behaviour, wayfinding, training) needs controlled, repeatable urban scenarios in which a real person is the pedestrian. Today those scenarios are:

1. **Hand-authored.** VR task frameworks (GUsT-3D) define guided user tasks, but an expert builds each environment and task list by hand.
2. **Vehicle-centred.** Scenario generators (Scenic, ScenicNL, ChatScene, ChatDyn, Traffic Scene Generation from NL) produce traffic for an AV under test. Pedestrians are NPCs or adversaries; no human performs a task.
3. **Not tied to real places.** 3D city generators (CityX, UrbanWorld, MetaUrban) give visual worlds without verifiable task semantics (goal, constraint, failure condition), and are not exportable to standard scenario formats.

**Problem:** there is no method that, from a real map area and a natural-language request, generates a *validated, standards-based* scenario (environment + dynamic traffic + guided pedestrian tasks) that a human pedestrian can play in VR/first person and that yields measurable task outcomes.

## 2. Research questions

* **RQ1 (representation).** Which task taxonomy and scenario representation capture guided pedestrian tasks in urban traffic while staying compatible with OpenSCENARIO/OpenDRIVE?
* **RQ2 (generation).** Can an LLM agent, grounded by map queries and a constrained DSL, produce executable scenarios for the task types from a prompt and an OSM area? How far does a small local model get?
* **RQ3 (validity).** Does map-aware automatic validation (geometry, surface, task feasibility, type rules) with a repair loop make generated scenarios valid and faithful to the prompt?
* **RQ4 (utility).** Do the scenarios elicit the intended behaviour and measurable outcomes when played by humans in VR/first person, compared with hand-authored ones?

### Revised scoping (agreed)
RQ1-RQ3 are answered without humans; RQ4 is exploratory and qualitative.
* **RQ1** by a *coverage analysis*: list the tasks reported in GUsT-3D, JaywalkerVR, CREATTIVE3D (road crossing), Robert 2023/2024 and the AV pedestrian-scenario papers, and show which fall inside the taxonomy and which are explicitly out of scope. (Needs a real read of those papers; abstracts alone are not enough.)
* **RQ2/RQ3** by an automatic benchmark: prompts x 7 types x model sizes x {with, without} validator loop; validity rate, repair iterations, prompt adherence (rule-checked against the prompt's stated constraints).
* **RQ4 (reworded):** "Are the generated scenarios playable and perceived as relevant by pilot users and domain experts?" A pilot (a few participants, e.g. rehabilitation specialists / lab colleagues), task-outcome logs from the player, think-aloud or short questionnaire; reported qualitatively, stated as a limitation, no inferential claims.

### Taxonomy: provenance and fixes
* **Source:** the five-row table (tab:ped_nav_tasks) in `main.tex`, justified there only as "common pedestrian behaviours reported in prior pedestrian-in-the-loop studies" with no citations. The two composite types (dep_comp, indep_comp) come from GUsT-3D-style task grouping and our implementation, not from that table. So the taxonomy is currently the authors' design, not derived from a specific published table. It must be grounded by the coverage analysis above.
* **Overlap fix:** present tasks as *Target + constraint set* rather than seven flat classes. Base task = reach a target; constraint axes = surface (walkable / road), path corridor, static obstacles, dynamic obstacles; composition axis = ordered / unordered. The five categories are canonical points on those axes; the two composites are the composition axis. This makes the overlap explicit and principled.
* **Missing families:** do not add types. State scope exclusions via the existing inclusion criteria (atomic, goal-oriented, measurable): signal compliance is a failure condition, not a task; crowd interaction, instruction-based wayfinding and perception tasks are future work.

## 3. State of the art (restructured 16 Nov 2026: three sections (3.1 to 3.3), at most four subsections each, with the papers to summarise)

How to read this: `[key]` = BibTeX key in `paper/refs.bib` (metadata checked against Crossref / DataCite on 16 Nov 2026; check against the full text before citing). `Zotero XXXXXXXX` = item in your Zotero library, no entry in `refs.bib` yet (export with Better BibTeX). `TO ADD` = found by search, not yet in `refs.bib`. Tags: **read** = read in full by the project; **abstract** = only abstract or search snippet seen; **unread** = listed only. Nothing below is a summary; each paper is a slot for your own sentences.
Suggested order: 3.1 specification and temporal logic (what is specified), 3.2 scenario generation (how scenarios are produced: LLM generation, scenes, agent techniques), 3.3 the human-in-the-loop side where this paper sits. Matrix at the end of this section.


### 3.1 Scenario specifications and temporal logic
#### 3.1.1 Scenario specification languages and their standards
**Standards and exchange formats**
* [asam_openscenario], [asam_opendrive] (ASAM standards). TO ADD: OpenSCENARIO DSL 2.0 manual (ASAM 2024; XML renamed "OpenSCENARIO XML", 2.x "OpenSCENARIO DSL").
* [molin2023specguided] Specification-guided critical scenario identification; compares OpenSCENARIO 2.0 with Scenic. **abstract**.
* [esmini] reference player used for the compatibility check; [dosovitskiy2017carla] CARLA.

**Declarative and probabilistic scenario languages, ontologies**
* [fremont2019scenic] Scenic (PLDI 2019) and [fremont2022scenic] Scenic (Machine Learning journal version); [vin2023scenic3] Scenic 3.0 (3D environments, falsification).
* Zotero scenario ontologies: Ulbrich 2015 (4JPQ8JTG), Menzel 2018 (J3YJDXUH), Bagschik 2018 (VYKWQ4VL, YBT8TZBC), Neurohr 2021 (JMP3L7FI), Costa 2024 (SPU4TMNS), Bogdoll 2023 (CB7JIPN2); GeoScenario.
* Gap sentence for your text: no standard covers a human pedestrian's guided tasks (carried here as a custom `<VRTask>`).

#### 3.1.2 Temporal logic and robustness
**Temporal logic, quantitative robustness and falsification (foundation of the specification language)**
* [maler2004monitoring] monitoring temporal properties of continuous signals (STL); [donze2010robust] robust satisfaction of temporal logic over real-valued signals; [fainekos2009robustness] robustness of temporal logic specifications.
* [corso2021blackbox] survey of black-box safety validation (names S-TaLiRo and Breach as the benchmark falsification tools). **abstract**.
* [ramezani2019semantics] two robustness semantics for falsification, driving example. **abstract**.

### 3.2 Scenario generation
#### 3.2.1 LLM-based scenario generation for driving (vehicle under test)
Planned length: 4 paragraphs, 400 to 500 words. Tags: **abstract** = only abstract or snippet seen, **unread** = title only. Descriptions are from abstracts, snippets or earlier notes: check against the full text before writing a claim.

**Paragraph 0 (lead-in): LLMs that generate formal specifications from text** (moved here from the specification subsection)
* [cosler2023nl2spec] nl2spec (CAV 2023): interactive NL to temporal logic, editable sub-translations. **abstract**.
* [chen2023nl2tl] NL2TL (EMNLP 2023). **abstract**.
* [liu2023lang2ltl] Lang2LTL: grounding complex NL commands to temporal tasks in unseen environments. **abstract** (check the CoRL 2022 workshop version versus the 2023 extension).
* Contrast to draw: these translate to LTL/STL for robots or verification; here the target is a typed language with margins, a library and validation against a map.

**Paragraph 1: text to executable scenario files**
* Point: pipelines that turn text into scenario or map files; compare on one axis (direct file output versus an intermediate language) and end with whether the output is validated.
* [text2scenario2025] Text2Scenario (arXiv 2503.02911; project page caixxuan.github.io/Text2Scenario.GitHub.io). **abstract**. LLM as parser that selects components from a hierarchical scenario repository; multi-stage few-shot prompting; CARLA; 533 safety violations in 368 scenarios. Whether it writes OpenSCENARIO is unconfirmed. **Read in full** (open on arXiv).
* [txt2sce2025] Txt2Sce: OpenSCENARIO from textual accident reports. **abstract**.
* [muller2025qcopendrive] LLM feedback loop with QC-OpenDRIVE for norm-adherent OpenDRIVE; checks XML schema plus a subset of the standard's rules; most errors found were schema violations. **abstract**. Closest to the repair loop. **Read in full** (DLR, available as a repository PDF).
* [lu2024mllmscenario] Multimodal LLM scenario testing: OpenStreetMap road geometry described in text and retrieved with embeddings (arXiv 2409.06450). **abstract**. The map-grounding aspect.

**Paragraph 2: pipelines with an intermediate representation**
* Point: a formal layer between the text and the simulator; this is the shape of your stage A / stage B. State the difference: a typed language with numeric margins, validated against a real map.
* [safa2026extendedscenic] LLM pipeline with an Extended Scenic DSL between free text and simulation scripts (arXiv 2602.20644). **abstract**. **Read in full** (open on arXiv).
* [target2023] TARGET: traffic rules to an intermediate DSL with syntactic and semantic validation, against hallucination (arXiv 2305.06018). **abstract**.
* [miceli2023dialogue] Dialogue-based generation of Scenic code for CARLA with validation feedback (arXiv 2310.17372); earlier notes: includes a pedestrian-crossing example. **abstract**.

**Paragraph 3: safety-critical and adversarial generation**
* Point: the goal is to find failures of the vehicle under test; a pedestrian is an adversary or background, never the participant.
* [zhang2024chatscene] ChatScene: LLM agent for safety-critical scenarios; controls adversarial objects such as pedestrians around an RL-trained ego vehicle. **abstract**.
* [elmaaroufi2024scenicnl] ScenicNL: probabilistic scenario programs (Scenic) from natural language (arXiv 2405.03709). **abstract**.
* [ruan2024ttsg] Traffic scene generation from natural language; reported lower accuracy on precisely timed events (a pedestrian stepping out); CARLA only. **abstract**.
* [chatdyn2024] ChatDyn: language-driven multi-actor dynamics in street scenes. **unread** (title).
* [yao2025agentsllm] AGENTS-LLM: agentic LLM that edits traffic scenarios with quality checks; earlier notes: works with small models. **abstract**.

**Paragraph 4: surveys and the gap**
* One sentence citing surveys instead of listing more generators: [zhao2025llmsurvey] (LLMs in scenario-based testing of ADS), [zhou2025genaisurvey] (generative AI for test scenario generation), Zotero 3P9JZTW3 (Gao 2025).
* The gap, to be written with "to our knowledge": these works target a vehicle under test; none has a human pedestrian performing a guided task; none specifies the task with numeric margins checked on the pedestrian's pose; none validates walkability against a real map. (The last two points come from your own method, `METHOD.md` sections 3 and 6.)
* Lead into 3.2.2.

**Further candidates (not needed for the four paragraphs)**
* [vargasrivero2025openx] Agentic generation of OpenX files (OpenSCENARIO, OpenDRIVE) from natural language (SAE 2025-01-0299). Not available to download anywhere (16 Nov 2026), so NOT cited: moved out of paragraph 1 on purpose; keep the bib entry only in case it becomes accessible.
* TO ADD: HASCO (Dagstuhl OASIcs AEiC 2026, paper 4, decouples semantic reasoning from syntactic generation); Chat2Scenario (OpenSCENARIO and CarMaker text from extracted scenarios). Do not cite AutoSceneGen: it was seen only on a summary page.
* Zotero, **unread**: Danso (XZND6B5E, year?), Asif (9RURWXTI), Xu real-to-sim (QZGQPDPB), ChatSim (CYRYYFBP), Zhong language-guided traffic diffusion (UQU8TVCR), Scenario Diffusion (WHKMP3MH), SurrealDriver (FXJTR2NJ), ML-SceGen (NALVY6KK).

#### 3.2.2 Urban and 3D scene generation (worlds without task semantics)
* [wu2025metaurban] MetaUrban (micromobility agents, RL-trained); [shang2024urbanworld] UrbanWorld; [zhang2024cityx] CityX. **abstract**.
* [yang2023holodeck] Holodeck (language-guided 3D embodied environments); [feng2023layoutgpt] LayoutGPT. **abstract**.
* Zotero: Text-Guided Editable 3D City (A9UWZFT9), Towards Autonomous Micromobility via Scalable Urban Simulation (LDRDADGG), CityCraft (LX7W87YP), Urban Architect (V6UP3DIK), Streetscapes (UNK29P3M), Scenethesis (3UVINWF7), SceneX (YJ7YI2SR), 3D-GPT (YM8E59Z5), ScenarioNet (8NYHVJND, year?), RoadGen (8BMZRTDE), survey Wen 2025 (ESJR3EQK). **unread**.

#### 3.2.3 LLM agent techniques the pipeline builds on
**Tool use and feedback loops**
* [yao2022react] ReAct; [schick2023toolformer] Toolformer; [shinn2023reflexion] Reflexion; [madaan2023selfrefine] Self-Refine. Relevant: the agent calls map tools, receives validator feedback and revises. **abstract**.

**Structured output and small models**
* [geng2023gcd] grammar-constrained decoding (EMNLP 2023); [willard2023outlines] efficient guided generation (Outlines). **abstract**.
* TO ADD (found by search, 2025 to 2026, check before citing): "The Constraint Tax" (arXiv 2605.26128, sub-3B models: schema validity up, accuracy down); "Good-Enough Structured Generation: a case study on JSON Schema" (NeurIPS 2025: grammar coverage gaps, validation in a feedback loop as an alternative); SLOT (arXiv 2505.04016); "Thinking Before Constraining" (arXiv 2601.07525). These bear on why validation plus repair is used here instead of constrained decoding.
* [yang2025qwen3] Qwen3 technical report (the model used is Qwen3.5-4B: cite its own report once you have the reference).

**Evaluating adherence to a text request**
* [murugadoss2024evaluator] evaluating the evaluator (LLM adherence to evaluation instructions). Zotero LogicBench (XHTJH6IC), PromptRobust (TE8XXMJE).
* Human rating of scenario-text match: Text2Scenario-style protocol (unread: check how its raters score) and this paper's 5-rater study.


### 3.3 Humans in the loop: guided tasks and pedestrians in VR (where this paper sits)
#### 3.3.1 VR task frameworks and LLM-generated VR content
Merged on purpose: cite GUsT-3D as the only task framework (the other task-based VR papers are more or less the same and are not cited), then the LLM-generated VR content papers below.
**VR task frameworks (closest framework)**
* [wu2022gust3d] GUsT-3D (Wu et al. 2022). **read** (PDF). Tasks as constraint lists over annotated scenes; authoring only, no generation.

**LLM-generated VR content and VR navigation tasks**
* [delatorre2023llmr] LLMR: real-time prompting of interactive Unity worlds. **abstract**.
* [qin2026navai] NavAI: LLM framework for navigation tasks in VR. **abstract**. Tasks appear researcher-authored (check).
* Zotero DZGMDY6Z (VELMA), GHDCLHAU (TravelAgent), G7W6IYJ8 (CityGPT), FGRL29D2 (prompt-based virtual worlds), 6AEH2X49 (GPT-VR Nexus), W2F5U278 (LearningverseVR), WTL5GW3N (MagicCraft). **unread**. TO ADD (found by search, 2026): DreamCodeVR (UCL, speech to runtime C# in Unity), CoGen3D (agentic co-design of VR assets); check titles and venues first.
* Not cited, dropped on purpose (similar to GUsT-3D): Zotero 2MRNL5DH task-based embodied VR (Robert 2023, SXHGZH89; Robert 2024, INEBJIPD; Robert 2022, Y76Y6VGJ), KBAILIFH (French DSL paper), 2IWK5KAS (Pirkovets), JYUE2MYZ (Ketoma 2023), XYTKCPP4 (Li 2020).

#### 3.3.2 Pedestrian road-crossing and traffic-interaction studies in VR
* [mukoya2024jaywalkervr] JaywalkerVR: safety-critical pedestrian-vehicle interactions in VR, scripted scenarios. **abstract**.
* [sobhani2017distracted] Distracted pedestrians' crossing behaviour with an immersive HMD (ITSC 2017). **unread**.
* [maruhn2021vrpedestrian] VR pedestrian simulator studies at home (Cardboard vs simulator). **unread**.
* TO ADD: Angulo et al., validation of a VR simulator against real-world pedestrian crossing (SSRN 2022, journal version Transportation Research Interdisciplinary Perspectives 2023: find the DOI); Mallaro et al. 2017 (HMD vs CAVE street crossing); Simpson, Johnston, Richardson 2003 (children's road crossing in a virtual environment, Accident Analysis and Prevention). Found only as search summaries: verify authors, year, venue.

#### 3.3.3 Pedestrians in scenario generation and simulation
**Pedestrians as adversaries for AV testing**
* Zotero: Spooner 2021 Ped-Cross GAN (UDJGVRGS), Yang 2023 Suicidal Pedestrian (DWQ72MNY), Yang 2025 critical pedestrian scenarios (5I7RI7QQ), Priisalu (6RCVNRU3, year?), survey Ding 2023 (7S6GS5MP). The human does not play the pedestrian.

**Real pedestrians in driving simulators (VR, motion capture, co-simulation)**
* [serrano2023carlavr] realistic pedestrian behaviour in CARLA using VR and mocap. **abstract**.
* [serrano2023digitaltwin] digital twin in VR for human-vehicle interaction (real crosswalk replicated in CARLA; behavioural gap). **abstract**.
* [mukoya2024jaywalkervr] (also 3.3.2). TO ADD: AR-PED (Simulation Modelling Practice and Theory 2019); Vissim-CARLA coupled pedestrian-in-the-loop work (title not yet identified).
* Contrast: scenarios there are hand-built; no generation, no task semantics.


### Notes for the section (not a subsection)
**Positioning matrix**
* Rows to include: GUsT-3D, JaywalkerVR, Scenic, ScenicNL, ChatScene, TARGET, Text2Scenario, LLM4AV, QC-OpenDRIVE feedback loop, Extended Scenic pipeline, MetaUrban, UrbanWorld/CityX, LLMR, NavAI, this work.
* Columns (the four conditions below plus two): human pedestrian performing the generated task; generated from a real map area; standard format output (OpenSCENARIO/OpenDRIVE); map-aware validation with repair; formal task specification with numeric margins; played in VR / first person.
* Safe claim and wording: section 4 below (never write "first").

**Reading priority and open checks**
1. Read in full, in this order: LLM4AV, Text2Scenario, QC-OpenDRIVE feedback loop, Extended Scenic pipeline, Agentic OpenX, Lang2LTL / nl2spec (for the lead-in of 3.2.1). These decide the novelty wording.
2. Citation searches still to do: Google Scholar "cited by" for GUsT-3D and JaywalkerVR (never run), plus a search on "pedestrian guided task generation LLM VR".
3. Cleanups: fill the "(year?)" Zotero items; TO ADD entries above (convert to BibTeX only after checking title, authors and year on the publisher or arXiv page).
4. Verification limits of 16 Nov 2026: metadata only (Crossref, DataCite, arXiv search results); no full text was read; descriptions of each paper in this file come from abstracts or search snippets.

## 4. Positioning
Closest papers by contribution overlap: **GUsT-3D** (tasks, no generation), **ChatScene / Scenic / ScenicNL / ChatDyn** (generation, no human pedestrian tasks), **JaywalkerVR** (human pedestrian in traffic, scripted), **MetaUrban / UrbanWorld / CityX** (urban worlds, no task semantics). This work sits at their intersection. Pipeline-level overlap also exists with **LLM4AV** and **Text2Scenario** (text -> validated OpenSCENARIO, vehicle-under-test).

### Novelty claim (agreed wording; check LLM4AV first)
Not novel on its own: LLM agent + validator loop; OSM -> OpenDRIVE; procedural 3D from OSM; LLM text -> OpenSCENARIO.
Novel combination (to our knowledge, four conditions together): (1) a **human pedestrian performing generated guided tasks** (not an NPC or adversary), (2) generated from a **real OSM area + text prompt**, (3) output as **standards-based OpenSCENARIO/OpenDRIVE with a `<VRTask>` extension**, (4) **map-aware validated** with a repair loop and played in VR / first person.
Safe sentence: "Existing LLM-to-OpenSCENARIO work targets vehicle-under-test scenarios; we generate pedestrian guided tasks for a human participant, grounded in a real map and played in VR or first person." Never write "first" without a systematic search (only 4 web searches and the Zotero library were checked; Google Scholar "cited by" on GUsT-3D and JaywalkerVR still to do).
5th contrib - Offering a open-source access to encourage ....

## 5. Notes
* Zotero has no file called "xr salento"; `main.tex` was used as the draft.
* Re-export the .bib from Zotero (Better BibTeX) rather than copying from this list; keys here are Zotero item keys.


COnfs:

Realistic	Simulation Modelling Practice and Theory (Elsevier)	A scenario-generation system with a benchmark is in scope, and a human study is not expected.	Moderate.
Realistic	Computers & Graphics (Elsevier)	Takes system and tool papers around VR and procedural content.	Moderate. A reviewer may ask for user evaluation.
Safe fallback	Virtual Reality (Springer)	Best topic match.	Reviewers there often expect a user study, so the pilot has to be solid.
Safe fallback	Multimedia Tools and Applications (Springer)	Accepts almost anything in scope.	Low prestige.
Stretch	IEEE Transactions on Intelligent Vehicles	Fits the scenario-generation side.	Needs strong baselines and a large benchmark. Rejection is likely without both.

## Acknowledgement and contributions (draft wording)
**Acknowledgements.** This work builds on ideas from prior research on guided user tasks in virtual-reality embodied experiences, in particular the GUsT-3D framework (Wu et al., 2022), and on discussions held during a postdoctoral position at [institution, year]. The author thanks [name] for those discussions. All software, the generation pipeline, the validator, the player and the experiments were designed and implemented by the author.

**Author contributions (CRediT).** [Author]: Conceptualization, Methodology, Software, Validation, Investigation, Formal analysis, Writing - original draft, Writing - review & editing, Visualization.

Notes (not for the paper): adjust "Conceptualization" if the taxonomy/ontology framing came from the postdoc; the acknowledgement should be accurate, not decorative. Check the contract's IP/publication clause before submitting.


## Scope decision: no RL/SFT; vision ablation instead
Decision: RL (and SFT) are out of scope for this paper because of time. They are listed as future work (cadrille-style SFT on validator-accepted (map, prompt) -> script pairs, then GRPO-style RL with the validator + adherence score as reward; inspiration: cadrille, CAD-Recode, Dr. GRPO/CPPO).

### Vision ablation (in scope; supports RQ2/RQ3)
Question: does giving the model a rendered view of the map improve generation, over text-only tools?
* **Conditions (same prompts, maps, seeds, validator loop):**
  1. text only (current system);
  2. text + top-down map image with feature ids labelled (needs a vision-capable model; check whether Qwen3.5-4B accepts images, otherwise use a VLM such as Qwen2-VL / Qwen2.5-VL of similar size and report the model change as a confound);
  3. (optional) text + image + VLM self-check of the rendered result against the prompt.
* **Metrics:** validity rate after repair, number of repair rounds, prompt adherence (rule-checked: target on requested surface, requested constraints present, requested ordering), per scenario type, per map.
* **Controls:** held-out maps, fixed prompt set (about 50 prompts x 7 types), several seeds, report variance.
* **Risks:** small VLMs are weak judges, so validate the VLM self-check against the rule-based adherence check before using it; image resolution/labelling choices are hyperparameters, report them.
* **Not claimed:** no training, so any gain comes from input modality only.


## Computers & Graphics: requirements from the Guide for Authors (read 2026-10-10)
* Template: LaTeX `elsarticle`, numbered refs in square brackets in order of appearance (`elsarticle-num`); >6 authors -> first 6 + et al.; DOIs where available; preprints marked "preprint"/server name. Single column for LaTeX is fine; .tex source required (PDF alone is not).
* **Double anonymized review:** separate title page (names, affiliation, corresponding email, **acknowledgements**, competing-interest declaration) and an anonymized manuscript (no names, no affiliations, **no acknowledgements**, no funding). Cite own work in third person. The acknowledgement drafted above goes ONLY on the title page. No repository/Zenodo links that reveal identity in the anonymized text.
* Abstract <= 250 words, no references. Keywords 1-7 (avoid multi-word with "and"/"of"). Sections numbered 1, 1.1, 1.1.1; abstract not numbered.
* Required at submission: **Highlights** (separate file, "highlights" in name, 3-5 bullets, <= 85 characters each); **Graphical abstract** (separate file, 531 x 1328 px h x w or proportional, readable at 5 x 13 cm; TIFF/EPS/PDF/MS Office); **CRediT** statement; **data statement** (Option C: deposit data/code in a repository and cite it, or state why not); **declaration of competing interests** (Word .doc/.docx); **funding statement** (suggested sentence for no funding: "This research did not receive any specific grant from funding agencies in the public, commercial, or not-for-profit sectors."); **cover letter** (< 1 page: contributions, full reference + status of closest prior art, how this differs; not funding/declarations/reviewer suggestions).
* **Generative AI declaration:** if AI tools were used in manuscript preparation, add a section before the references ("Declaration of generative AI and AI-assisted technologies in the manuscript preparation process") naming tool and reason. Not needed for grammar/spelling/reference checks. AI-made figures/diagrams must be disclosed in each caption. Decide honestly what counts (literature search help, drafts, code, diagrams).
* Figures: separate files, vector (EPS/PDF) or >= 300 dpi photos; line art bitmap >= 1000 dpi; colour-blind-safe; every figure cited in text; captions required. Tables as editable text, no vertical rules or shading.
* Preprints on arXiv/SSRN are allowed and not prior publication. Not under consideration elsewhere. Authorship fixed at submission (changes need editor approval).
* No page or word limit is stated in the guide.
* Optional: GRSI Replicability Stamp (code/data certified, badge) and a Software Impacts article for the software.
* Aims/scope fit: interactive computer graphics, virtual environments, novel interaction, applications of CG; tutorial/state-of-the-art also welcome. Frame the paper as a VR/interactive-graphics systems & application paper.
* Human pilot (RQ4): check whether the pilot needs an ethics approval or consent statement before running it; the guide does not state it, the institution does.


## RQ4 decision: small qualitative round (option 2, chosen)
* **What:** 3-5 adult volunteers play 2-3 generated scenarios (VR if a headset is available, otherwise first-person) and give informal opinions: understandable? tasks sensible? plausible? anything confusing?
* **Reported as:** exploratory, opinion-based, qualitative only; no statistics, no comparison claims; explicitly listed as a limitation.
* **No institutional ethics review applies (independent author).** State this in the paper. Mitigations: voluntary, informed verbal/written consent, may stop at any time, anonymous, no personal data (no names, no video, no demographics beyond what is needed), player logs only task outcomes and positions, short sessions with clear space (motion sickness is the main VR risk).
* **To do before running it:** write a one-page consent text; fix the 2-3 scenarios (different task types, held-out map); prepare 5-6 open questions; test the headset path first (VR is still untested on hardware); store feedback without identifiers.
* **Where it appears:** a short section in the evaluation, mapped to RQ4, plus the limitations paragraph.


What the submission also needs:

Two versions of the paper.
An anonymized manuscript, with no names, affiliation, acknowledgements or funding.
A separate title page with names, address, corresponding email, acknowledgements and the declarations.
Highlights file: 3–5 bullets of at most 85 characters each, with “highlights” in the file name.
Graphical abstract: a separate image file.
Declarations:
the competing-interests statement, as a Word file
a CRediT author statement
a funding statement
a data availability statement
the generative AI disclosure section, if it applies
Cover letter: under a page, listing the closest prior art with full references and how your work differs.
Figures as separate files (vector or high resolution), each cited in the text and captioned.
A repository for code and data (for example Zenodo), referenced with an anonymous link in the review version.



## Scope decision: two task kinds only (go, cross)
* In scope: the two task kinds in `VRTask.kind`: `go` (reach a target) and `cross` (cross a road at a crossing). Everything else is a constraint on those two (surface, path corridor, static obstacles, moving obstacles, signal) or a composition of several tasks (ordered / unordered). The 7 named types are points on those axes.
* Out of scope, stated as future work: object interaction (GUsT-3D-style `movable` / `container` / `actable` layers, e.g. picking up trash and putting it in a bin, take/place actions, inventory), crowd interaction, instruction-based wayfinding, perception tasks. Justification: the inclusion criteria (atomic, goal-oriented, measurable navigation tasks tied to the road or its surroundings) and the fact that GUsT-3D already covers object interaction in Unity.
* Consequence for the taxonomy coverage analysis (RQ1): classify tasks reported in GUsT-3D, JaywalkerVR, CREATTIVE3D etc. as inside (go/cross + constraints) or outside (object interaction) and say so.

### Correction to the scope above (task primitives)
`cross` is not a separate primitive: it is `go` (reach a target) with a crossing-side target and default signal/crosswalk failure conditions; the player never branches on `kind`. (Historical note, superseded by FINAL STATE below: at the time there was one hard-coded primitive, Reach.) Candidate further primitives, each defined by WHAT is evaluated (GUsT-3D evaluation-time idea: at a time / at some point / at all times):
* Reach: position at the end (existing; `go`, `cross` = preset).
* Wait/Hold: position (zone) over an interval or until an event (signal green, vehicle passed).
* Look/Attend: head/camera orientation toward an entity or area at some point (e.g. check traffic, look at the light; cf. GUsT-3D LookAt).
* Follow: relative distance to a moving entity over an interval (guided walking).
Proposed minimal set: Reach, Wait, Look (+ Follow optional). Together they express the real crossing procedure: wait at kerb -> look -> cross. Decision pending; code unchanged.


## FINAL STATE OF THE METHOD (implemented; supersedes the "pending" notes above)
* Decisions taken and implemented: ONE task form (a goal formula + safety formulas; "reach a target" is only the most common goal) written in a typed specification language (atoms with numeric margins, temporal
  combinators, named definitions; the model may write its own at level L2); the 7 types are named points on constraint axes derived from the formulas; `cross` is a library
  definition, not a task kind; Wait/Look/Follow/KeepClear/Pace are library definitions (no code needed per primitive); Respond and object interaction are out of scope.
* Two-stage generation: stage A = specification as data (never executed), stage B = world script in the sandbox; validator + nominal walker; auto-placement of the participant.
* The player monitors the formulas on the real pose (10 Hz trace, interval robustness) and reports margins; Python and TypeScript monitors are tested against each other.
* Evaluation protocol and results: `paper/METHOD.md` sections 8-9, `paper/results/summary.md`. RQ1 = taxonomy as axes + coverage analysis (still to be done by reading GUsT-3D,
  JaywalkerVR, CREATTIVE3D tasks), RQ2/RQ3 = benchmark (done), vision ablation = NOT done (needs a vision-capable model; Qwen3.5-4B accepts text only here), RQ4 = qualitative round (not done).
* Read `paper/METHOD.md` first: it is the full technical description with the worked example, the verification table and the limitations.
