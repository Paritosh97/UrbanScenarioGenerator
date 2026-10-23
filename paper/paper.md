# Problem, research questions and state of the art

Source: the whole Zotero library (376 items; "Closest" subcollection marked ★) and the introduction/related work of `urbanscenariogenerator_osm/main.tex`.
Citations are given as Author Year (Zotero key). Items whose Zotero record has no year/venue are flagged "(year?)": check before citing.

## 1. Problem

Studying how people walk in cities (low-vision rehabilitation, road-crossing behaviour, wayfinding) needs controlled, repeatable urban scenarios in which a real person is the pedestrian. Today those scenarios are:

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

## 3. State of the art

### A. Pedestrians in the loop and VR experiments
Wu 2022 GUsT-3D (XQHTD8EV) is the closest framework for guided tasks and ontology (Target, FailureCondition): authoring only, no generation. Mukoya 2024 JaywalkerVR (2MRNL5DH) collects safety-critical pedestrian-vehicle interactions in VR; scenarios are scripted. Robert 2023 (SXHGZH89), Robert 2024 (INEBJIPD), Robert 2022 (Y76Y6VGJ) and a French DSL paper (KBAILIFH) give task-based and DSL-based embodied VR experiences. Gallo 2024 DiVR (I7L5AAN4) and Gallo 2024 low-vision trajectory forecasting (8MB4688H) plus the CREATTIVE3D dataset (8N3BV3JB, year?) supply behaviour data under simulated low vision. Pirkovets (2IWK5KAS), Ketoma 2023 (JYUE2MYZ) on authoring/personalising VR training, Li 2020 (XYTKCPP4) wheelchair training scenario synthesis.

### B. Low-vision simulation and rehabilitation in VR
Zotero "Low Vision Simulation" (52 items) including REALTER (Barbieri 2023/2024), Ricci 2023 (N9M2N5WL), Delachambre 2024 AMD Journee (W2P3VFBP), Neugebauer 2024, Jones 2018/2020. These supply perceptual manipulations; none generates the walking tasks.

### C. Scenario specification and ontologies
Ulbrich 2015 (4JPQ8JTG), Menzel 2018 (J3YJDXUH), Bagschik 2018 (VYKWQ4VL, YBT8TZBC), Neurohr 2021 (JMP3L7FI), Costa 2024 (SPU4TMNS), Bogdoll 2023 (CB7JIPN2); languages: ASAM OpenSCENARIO/OpenDRIVE, GeoScenario, ★Scenic Fremont 2019 (SUH9HKUQ), Scenic 3.0 Vin 2023 (ZTIXE8JL). Gap: pedestrian guided tasks are not part of any standard; we carry them as a custom `<VRTask>` in a CustomCommandAction.

### D. LLM-based driving scenario generation
★ChatScene Zhang 2024 (9YZQPVXJ), ★Traffic Scene Generation from NL Ruan 2024 (VHUIC5S9), ★ChatDyn Wei 2024 (Q5AAP5H4), ScenicNL Elmaaroufi 2024 (82V93SQZ), Txt2Sce 2025 (64VNRMI7), ML-SceGen 2025 (NALVY6KK), Danso (XZND6B5E, year?), Asif (9RURWXTI), Xu real-to-sim (QZGQPDPB), ChatSim Wei 2024 (CYRYYFBP), Zhong 2024 language-guided traffic diffusion (UQU8TVCR), Scenario Diffusion (WHKMP3MH), SurrealDriver Jin 2024 (FXJTR2NJ), survey ★Gao 2025 (3P9JZTW3). All target vehicles/AV testing; none produces a task for a human pedestrian.

### E. Pedestrian-focused scenario generation for AV testing
Spooner 2021 Ped-Cross GAN (UDJGVRGS), Yang 2023 Suicidal Pedestrian (DWQ72MNY), Yang 2025 critical pedestrian scenarios (5I7RI7QQ), Priisalu (6RCVNRU3, year?), survey Ding 2023 (7S6GS5MP). Pedestrians are the adversary; the human does not play them.

### F. Urban and 3D scene generation
★MetaUrban Wu 2024 (BHYANUVF), ★UrbanWorld Shang 2024 (KTIBJCGS), ★CityX Zhang 2024 (PMM5EV44), ★Text-Guided Editable 3D City Feng 2025 (A9UWZFT9), ★Towards Autonomous Micromobility via Scalable Urban Simulation (LDRDADGG), CityCraft (LX7W87YP), Urban Architect (V6UP3DIK), Streetscapes (UNK29P3M), Holodeck (SUDP49QI), LayoutGPT (7TVBN68J), Scenethesis (3UVINWF7), SceneX (YJ7YI2SR), 3D-GPT (YM8E59Z5), ScenarioNet (8NYHVJND, year?), RoadGen (8BMZRTDE), survey Wen 2025 (ESJR3EQK). Visual/physical fidelity, no task semantics or standard export. Closest in spirit: MetaUrban (pedestrian/micromobility agents), but agents are RL-trained, not human.

### G. LLM agents, urban LLMs and VR content creation
TravelAgent Noyman 2024 (GHDCLHAU), VELMA (DZGMDY6Z), CityGPT (G7W6IYJ8), Roberts 2022 prompt-based virtual worlds (FGRL29D2), GPT-VR Nexus (6AEH2X49), Song 2024 LearningverseVR (W2F5U278), MagicCraft (WTL5GW3N). LLMs author VR content, but without map-grounded validation or tasks.

### D2. Added after the online cross-check (from search snippets, NOT yet read in full; verify before citing; not yet in Zotero)
* **LLM4AV** (Springer chapter, 2026; doi/link: link.springer.com/chapter/10.1007/978-981-95-6426-2_9): text -> DSL -> OpenSCENARIO 1.x on OpenDRIVE geometry chosen by rule-based map retrieval; multi-layer validator (XML syntax, kinematic feasibility, behaviour consistency); example includes a mid-block pedestrian crossing. **Closest pipeline-level competitor: read first.**
* **Text2Scenario** (arXiv 2503.02911, 2025): free text -> executable `.xosc`, GPT-4 prompt pipeline, AV testing.
* **AGENTS-LLM** (arXiv 2507.13729, 2025): agentic LLM that edits traffic scenarios from NL with quality checks; works with small models.
* **Dialogue-based generation of self-driving scenarios with LLMs** (arXiv 2310.17372, 2023): Scenic code for CARLA with validation feedback; includes a pedestrian-crossing example.
* **NavAI** (arXiv 2601.03251, 2026): LLM framework for navigation tasks in VR (scene screenshots -> navigation intent -> controls). Tasks appear researcher-authored, not generated.
* **Walk-the-Talk** (2024): LLM-driven pedestrian motion generation from text (NPC motion, not OpenSCENARIO).
* **AR-PED** (Simul. Model. Pract. Theory 2019): AR pedestrian-in-the-loop simulation framework.
* Surveys: arXiv 2505.16587 (LLMs in scenario-based testing of ADS, IEEE T-ITS), arXiv 2512.15422 (generative AI for ADS test scenario generation).
* Not verified / ignored: PlannerForge, STADA (only titles seen). OpenSCENARIO 2.1 compiler for CARLA (arXiv 2604.16452) is relevant only if targeting XOSC 2.x.

### H. Evaluating LLM adherence and logic
Murugadoss (AULQFZCY, year?), LogicBench Parmar 2024 (XHTJH6IC), PromptRobust Zhu 2024 (TE8XXMJE). Relevant for RQ2/RQ3 evaluation design.

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


## EVALUATION DECISION (latest)
* Main result = L2 only, per scenario type, on a real map (Sophia Antipolis / Biot): table with scenario type, task description, quantitative metric, result (`paper/results/table_l2.tex`, `\input` in paper.tex; prompts in Appendix A). L0/L1 and the vision run are optional ablations, not the evaluation. Results and the pilot/tuning history to disclose: `paper/METHOD.md` section 9.
