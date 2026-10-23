# Architecture notes

## One frame, one map
`osm.build_map` projects OSM **once** into a local East-North frame (metres, heading 0 = east, CCW). Everything reads that metric model:
the validator, the agent's tools, the nominal walker, the player, `scene_map.json`, and `map.xodr` (OpenDRIVE, same coordinates, roads trimmed
at junctions plus connecting roads). The map is JSON-rounded before validation so the sandbox child (which loads `scene_map.json`)
and the host see identical numbers.

## A task is a goal plus rules, written in a small formal language (`usg.spec`)
Every guided task is **one primitive**: *reach a target*, plus constraints. Instead of fixed task classes, the constraints are written in a typed
specification language, so the same machinery expresses reaching, waiting, looking, following, keeping clear and pacing.

| layer | what | where |
|---|---|---|
| entity types | the map-derived classes (road, sidewalk, crosswalk, crossing, vehicle, walker, signal) | `mapmodel.py`, `surface_at` |
| atoms | `in_zone`, `on_surface`, `near_path`, `dist_le/ge`, `look_at`, `speed_le/ge`, `signal_is`, `event`, `true`; each returns a **signed margin** (metres, degrees, m/s, or +-1) | `spec/formula.py` (catalogue), `spec/monitor.py` (semantics) |
| combinators | `not and or implies eventually always until then prev` with time windows in seconds from the task start | same |
| definitions | a standard library (`reach`, `hold`, `wait_for_green`, `look`, `follow`, `keep_clear`, `pace`, `cross`, `collision_free`, `stay_on`, `stay_near_path`, `obey_signal`, `no_event`) and, at level 2, definitions the model writes itself | `STD_LIB`, `check_defs`, `expand` |

A task has a **goal** formula (it succeeds when the goal is satisfied) and a list of **safety** formulas (it fails as soon as one is violated), plus two
timeouts (a hint at `initial`, failure at `baseline`), instructions, and ordering (`after`, group modes). The old helpers `go_to`, `cross`,
`follow_path` are now shorthand that *compile to the same formulas* (`ScenarioBuilder._compile_legacy`), so there is one evaluation path.
The 7 scenario types of the paper are named points on constraint axes (`spec/axes.py`: surface, path, static, dynamic, signal, composition);
the axes of any scenario are **derived from its formulas**, not from per-type code.

### Quantitative semantics (`spec/monitor.py`, mirrored in `player/src/runtime/monitor.ts`)
`Monitor.rho(formula, k)` returns an interval `(lo, hi)` on a trajectory *prefix*:
`lo >= 0` means already satisfied whatever happens next, `hi < 0` already violated, otherwise undecided. With a complete trace `lo == hi` is the usual
signal-temporal-logic robustness (a margin in the unit of the atoms). The player evaluates each task at 10 Hz against the **real** pose of the participant
and reports the margins; Python and TypeScript are compared on 160 random formulas x 12 prefix/anchor settings (`player/tests/spec.test.ts`).

## The pipeline (three levels, compared in the evaluation)
* **L0 (the original system):** the model fills in a Python script that calls the task helpers.
* **L1:** stage A, the model writes a *specification* (data) from the library; stage B, a world script (user, vehicles, signals) that calls `scenario.apply_spec(SPEC)`.
* **L2:** like L1, and the model may define its own definitions (`defs`), still evaluable because only implemented atoms appear in them.

Stage A is never executed. `spec.document.check_document` parses/type-checks it, resolves map references, checks walking feasibility and tells the model which
entities and signals the script must create. Stage B runs in the sandbox; its checks that used to be seven hand-written archetype rules are now derived from the
formulas (a keep-clear rule on a moving entity needs a mover whose route meets the participant's path, and so on). A **nominal walker** (`spec/oracle.py`) walks the
route through the goal zones, waits for green, yields to traffic and keeps its gaze on look targets, and the same monitor evaluates the formulas on that trace; a
negative margin is reported as a warning. It is an offline validation device only: the player never moves the participant.

## What the LLM does and does not do
The model is an **agent** (`agent/loop.py`): the harness pre-fetches the map overview, the reference script and (L1/L2) a reference specification derived from it;
the model adapts them, calls grounded tools (`list_features`, `check_point`, `plan_route`, `list_atoms`) when it needs an id, and repairs from precise validator
messages. The tool format is plain text (`<tool name="...">{json}</tool>`) because small models handle it more reliably than native function calling.
`ScenarioBuilder` assembles the OpenSCENARIO storyboard deterministically; the model supplies content only. If a script omits `scenario.user(...)` while applying a
specification, the participant is placed automatically ~18 m (route distance) before the first goal zone.

## Scenario encoding
OpenSCENARIO 1.3 via `scenariogeneration`: inline `Pedestrian`/`Vehicle` entities, `Init` teleports and signal states, stories for user tasks, NPC trajectories and
signal phases, a `StopTrigger`. Pedestrian tasks are `UserDefinedAction/CustomCommandAction type="VR_TASK"` with a real `<VRTask>` child (goal, target, instructions,
feedback, dependencies, group mode, timeouts and a `<Spec>` element holding the goal and safety formulas as `<F op="...">` trees). Task order uses standard
`StoryboardElementStateCondition`s. Other tools that ignore custom commands still load the file.

## The player (`player/`, served at `/player`)
React + three.js + @react-three/xr, built into `src/usg/player_dist`. `runtime/xosc.ts` parses the scenario (including `<Spec>`); `runtime/sim.ts` interprets
acts/events/conditions, moves vehicles and walkers, cycles signals, and evaluates every task's formulas against the REAL pose (head in VR, camera in first person):
the task succeeds when the goal's `lo >= 0`, fails when a safety rule's `hi < 0` (reporting that rule's label, e.g. "crossed on red") or at the baseline timeout.
`runtime/surface.ts` is a line-for-line port of `MapModel.surface_at` (tested on 13,440 points). The inspector (press I) shows the live pose, every task's formulas with
their current margins, and all OpenSCENARIO events. Results (per task outcome and margins, plus a 10 Hz trace) can be downloaded.

## One server
`app.create_server` mounts the Gradio UI at `/`, the static player at `/player/`, and `GET /packages/<token>.json` for generated scenarios (random 128-bit tokens).

## Evaluation (`scripts/benchmark.py`, `scripts/summarize_benchmark.py`)
32 prompts (the 7 types, mixed prompts that need waiting/looking, and a real Munich map) x pipelines L0/L1/L2 x repetitions, scored automatically:
validity, first-try validity (= no repair loop), adherence (the scenario's constraint axes equal the requested ones; required operators occur) and satisfiability
(nominal-walker margin). A model-free keyword baseline is scored the same way. Results: `paper/results/`.

## Extending
* New atom: implement it in `spec/monitor.py` and `player/src/runtime/monitor.ts`, add it to `ATOMS`/`CATALOG`/`_ALLOWED_FIELDS` in `spec/formula.py`, add a case to the random generator in `scripts/make_player_fixtures.py` (the parity test then covers it).
* New library definition: add it to `STD_LIB` (it is plain JSON in the language itself) and, for a participant-facing failure message, to `_REASONS` in `dsl/builder.py`.
* A different player/engine: consume `scenario.xosc` (+ `<Spec>` formulas) and `scene_map.json` from the Result downloads.
