# Method map: which file to read for which part of the method

Paths are relative to `usg/`. This is a reading guide, not paper text. Function names were taken from the code (grep of `def`/`class`); line numbers are deliberately left out because they drift. Deep detail lives in `paper/METHOD.md` (Part I: pipeline, Part II: every constant) and `docs/EVALUATION.md`.

## 0. Suggested reading order (about 2 hours)

1. `paper/METHOD.md` §0 and §1 (idea in five sentences, data flow).
2. `paper/METHOD.md` §3 (task model) with `src/usg/spec/formula.py` and `spec/monitor.py` open next to it.
3. `src/usg/tools.py` (what the agent can call), then `src/usg/agent/loop.py`.
4. `paper/METHOD.md` §4 and §6, then `tests/test_toolserver.py` and `tests/test_spec.py` (the tests are the most compact statement of the rules).
5. `paper/METHOD.md` §8 and §9.0, then `scripts/benchmark.py`.

## 1. Pipeline at a glance

OSM area + prompt -> `osm.build_map` -> `MapModel` -> agent (tools) -> **stage A** `submit_spec` (spec as data, checked) -> **stage B** `submit_script` (world script calling `scenario.apply_spec(SPEC)`, run in sandbox) -> validator + nominal walker -> OpenSCENARIO + OpenDRIVE package -> player (three.js / WebXR) with the live monitor.
Doc: `METHOD.md` §1.

## 2. Map model (real OSM -> simulation world)

| Part | File | Look at |
|---|---|---|
| Fetch/parse OSM, roads, sidewalks, junctions | `src/usg/osm.py` | `bbox_from_center`, `fetch_osm`, `parse_osm`, `build_map`, `_junction_geometry` |
| Data model (Road, Crossing, Signal, Prop, Building, Area, Path...) and `surface_at` | `src/usg/mapmodel.py` | dataclasses, `MapModel` |
| Projection | `src/usg/geo.py` | `Projection` |
| Pedestrian routing graph | `src/usg/pedgraph.py` | `PedGraph` |
| Signals/crossing cycles | `src/usg/signals.py` | |
| OpenDRIVE export | `src/usg/xodr.py` | `export_xodr` |
| Synthetic test city | `src/usg/synth.py` | |
| TS port of surface rule | `player/src/runtime/surface.ts` | must match `surface_at` |

Doc: `METHOD.md` §2, Part II A to K, S (known simplifications).

## 3. Task model and specification language (core of the contribution)

| Part | File | Look at |
|---|---|---|
| Language: node types, combinators, atoms with margins, library ops | `src/usg/spec/formula.py` | `check_node`, `check_defs`, `expand`, `prepare`, `measure`, `atoms_in`, `entities_in`, `signals_in`, STD_LIB |
| Quantitative semantics (interval robustness over a trace) | `src/usg/spec/monitor.py` | `Sample`, `atom_value`, `Monitor`, `goal_status` (decision rule) |
| Constraint axes (surface/path/static/dynamic/signal/composition) | `src/usg/spec/axes.py` | `task_axes`, `scenario_axes`, `category_of`, `composition_unordered`, `_calls` |
| Spec document (tasks + defs), semantic check | `src/usg/spec/document.py` | `document_from_spec`, `check_document`, `feedback_text` |
| Nominal-walker oracle (is the spec satisfiable by a compliant walk?) | `src/usg/spec/oracle.py` | `nominal`, `build_movers`, `margins`, `_plan`, `_gates` |
| Task object and scenario encoding | `src/usg/dsl/core.py`, `src/usg/dsl/builder.py` | `VRTask`, `MapQuery`, `Place`; `ScenarioBuilder`, `apply_spec`, `when_task_starts/done`, `_LAST_HANDLES` |
| Seven scenario types + mixed, per-type checks | `src/usg/scenario_types.py` | `_check_*`, `axes_of`, `classify` |
| TypeScript twin (parity with Python) | `player/src/runtime/{formula,monitor,geometry,xosc,types}.ts` | compare with Python files |

Doc: `METHOD.md` §3.1 to §3.6. Tests: `tests/test_spec.py` (language, monitor, parity), `tests/test_pipeline.py`.

## 4. Generation: agent, tools, levels

| Part | File | Look at |
|---|---|---|
| Agent loop: tool-call parsing, tolerant JSON repair, context compaction, rescue | `src/usg/agent/loop.py` | `parse_tool_call`, `_tolerant_json`, `_repair_brackets`, `compact`, `run_agent` |
| Tools exposed to the model (map queries, `submit_spec`, `submit_script`, level-dependent tool set) | `src/usg/tools.py` | `tool_specs(level)`, `ToolServer`, `t_submit_spec`, `t_submit_script`, `system_prompt` |
| Prompts | `src/usg/agent/prompts/` | `system.md`, `system_spec.md`, `system_spec_auto.md`, `dsl_reference.md`, `dsl_world.md`, `spec_reference.md` |
| Grounded first message and grounding checks | `src/usg/grounding.py` | `requested_ids_text`, `inventory_text`, `corridor_errors`, `surface_rule_errors`, `intent_errors`, `grounding_errors`, `refusal_text` |
| Assisted tier (deterministic repair of the world script) | `src/usg/assist.py` | `world_script`, `_anchor_crossing`, `fallback_script`; `ToolServer.assist_world()` |
| LLM clients (LM Studio / local) | `src/usg/llm.py`, `src/usg/localllm.py` | |

Levels: L0 script + helpers, L1 spec from library + world script, L2 spec with own definitions + world script. Doc: `METHOD.md` §4 and §8. Tests: `tests/test_agent.py`, `tests/test_toolserver.py`, `tests/test_grounding.py`, `tests/test_assist.py`, `tests/test_localllm.py`.

## 5. Verification (what "accepted" means)

| Part | File | Look at |
|---|---|---|
| Sandbox: policy check, subprocess, limits (120 s, safe builtins) | `src/usg/sandbox.py` | `check_policy`, `run_script`, `execute_script`, `SandboxResult.feedback` |
| Scenario validator (placement, surfaces, entities, signals, per-task checks) | `src/usg/validate.py` | `validate`, `_check_specs`, `check_archetype` |
| Standards check (esmini, OpenSCENARIO/OpenDRIVE load) | `src/usg/esmini.py`, `scripts/check_standards.py`, `src/usg/storyboard.py` | `find`, `run`, `ok`; result in `paper/results/standards_check.md` |

Doc: `METHOD.md` §6. Order of gates for one submission: spec schema/semantics (`check_document`) -> grounding checks -> world script in sandbox -> validator -> nominal walker (`spec/oracle.py`).

## 6. Player and runtime monitoring

- `player/src/runtime/sim.ts` (simulation loop), `monitor.ts` / `formula.ts` (same semantics as Python), `pedroute.ts`, `surface.ts`, `xosc.ts` (reads the exported file).
- `player/src/scene/{world,props,entities,snapshot}.ts`, `SceneView.tsx` (3D world from the map).
- Built output: `src/usg/player_dist`. App glue: `src/usg/app.py` (Gradio, package format `usg-scenario-package/1`).
- Doc: `METHOD.md` §5, Part II P and Q.

## 7. Evaluation

| Part | File | Look at |
|---|---|---|
| Benchmark runner, metrics (accepted, assisted, valid_output, first_try, attempts, adherent) | `scripts/benchmark.py` | `score`, `run_one`, `baseline` |
| Prompts | `eval/prompts_{munich,paris_center,sophia}.json`, `scripts/make_prompts.py` | |
| Tables, Wilson CIs, sign tests | `scripts/final_tables.py`, `scripts/summarize_benchmark.py` | outputs `paper/results/summary.md`, `table_levels.tex`, `table_types.tex` |
| Raw data | `paper/results/final_<map>_l{0,1,2}.jsonl` | |
| Rating study (items, server, ICC, bootstrap) | `scripts/rating.py` | `sheet`, `serve`, `summary`; guide at the end of `docs/EVALUATION.md` |

Doc: `METHOD.md` §8 (protocol), §9.0 (final results), §11 (limitations); `paper/NOTES.md` §7a (final numbers and claims).

## 8. Things to verify yourself while reading (claims the paper will make)

1. Python and TypeScript monitors agree: `tests/test_spec.py` parity tests; compare `monitor.py` with `monitor.ts`.
2. Decision rule (violated / satisfied / failed) in `monitor.py: goal_status`.
3. Surface rule in Python vs TS (`mapmodel.py: surface_at` vs `surface.ts`).
4. What the assisted tier changes versus model-only (`assist.py`, `tools.py: assist_world`), since it is reported separately.
5. The harness supplies grounded context to the model (`grounding.py: requested_ids_text`); state this in the paper.
6. The system was developed on failures of the same 50 prompts (v1 to v6, `METHOD.md` §8); final numbers combine v5 and a v6 rerun of four types. Disclose.

## 9. Mapping to the paper sections

- Methods: map model (§2 above) -> task model and language (§3) -> semantics -> generation framework (§4) -> verification (§5) -> player (§6).
- Evaluation setup: §7 above, plus where to cite ReAct, Reflexion, structured-output papers (see `paper/paper.md` "Notes for the section").
- Results/discussion: `METHOD.md` §9.0 and §11.
