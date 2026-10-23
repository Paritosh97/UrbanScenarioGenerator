# Urban Scenario Generator

Pedestrian **guided-task scenarios** from OpenStreetMap + a text prompt. A local LLM agent plans the scenario, a map-aware validator
checks it, and one button opens it as a walkable **WebVR / first-person** scenario in your browser. You are the pedestrian.

```
 map area (OSM)  +  prompt
        │
        ▼
  osm.py ── one metric map (roads, sidewalks, crossings, signals, props, buildings) ─┬─ scene_map.json
        │                                                                             └─ map.xodr (OpenDRIVE, same coordinates)
        ▼
  agent loop (local Qwen, started from your LM Studio files) ⇄ grounded tools: list_features, check_point, plan_route, list_atoms, templates
        │
        ├─ stage A  task SPECIFICATION (JSON, never executed): goal + safety formulas in a typed constraint language ── checked against the map
        └─ stage B  world script on the pedestrian DSL (user, vehicles, signals) + scenario.apply_spec(SPEC)
        │   policy check → sandboxed subprocess → map-aware validator (+ nominal walker) ── errors go back to the agent to repair
        ▼
  OpenSCENARIO (.xosc) with <VRTask><Spec> formulas ──►  [Open in WebVR]  ──►  three.js / WebXR player (new tab) that MONITORS the formulas live
                                                       VR headset if present, else first person (WASD + mouse)
```

## Run it

```bash
pip install -e ".[dev]"            # Python >= 3.10  (use a venv)
python -m usg.cli app              # http://127.0.0.1:7860
```

1. **Map** tab: *search* for a place in the search bar, zoom to the street you want, then press **Draw area** and drag a rectangle (at most 1 km²) or **Use current view**.
   Press **Load map of the selected area** (Overpass download, cached in `.usg_cache/`). *Use the sample city instead* needs no network; an `.osm` file also works.
2. **Generate** tab: the local model is already loading (status line); describe the task and press *Generate scenario*. The agent log streams live. Below the log the
   **task specification (JSON)** and the **world script (Python)** appear in two editors: change either and press **Validate & build my edits** (no model needed).
   *Advanced* has the step limit, temperature and the optional map image. The pipeline is always L2.
3. **Result**: press **Open in WebVR**. A new tab opens the player: *Enter VR* if a headset is detected, otherwise first person.
   Also shown: task table (goal, rules, nominal margin), overlay map, the OpenSCENARIO storyboard, and downloads (`.xosc`, `.xodr`, map JSON, script, `spec.json`, package).

**Hard checks against the map.** If the request names something the map does not contain ("walk to the waste basket" where there is none, "wait for the pedestrian light" without a
signalised crossing), generation is refused before the model runs and the log lists what the map does have (`usg/grounding.py`). If the map has it but the generated
specification or script never goes there, the submission is rejected and the nearest ids are listed.

One server hosts everything: Gradio at `/`, the player at `/player/`, scenario packages at `/packages/<token>.json`.

### The player (what you see and what is live)
* **You are the ego pedestrian.** Nothing scripts or simulates you: in VR your head/room-scale walking is the position (left stick moves, right stick snap-turns);
  on desktop WASD + mouse + Shift.
* **Guided tasks** with live timers, distance, success/failure messages, ordering (dependent / independent groups), collisions, signal violations,
  corridor and surface rules, timeouts.
* **The scenario runs around you**: vehicles and walkers follow their OpenSCENARIO trajectories, signals cycle, events start from their triggers.
* **Inspector** (press **I**): your real position and the surface you stand on, every OpenSCENARIO event with its state (running / waiting for *what* / completed) and
  its actions, vehicles and walkers with speed, signal states.
* **Results**: at the end *Download results (JSON)* gives per-task outcome, timing, closest vehicle distance and your 10 Hz walking trace.

### Headsets
WebXR only works on HTTPS or `localhost`.
* **Tethered** (Quest Link / Air Link / SteamVR): press the button in Chrome or Edge on the same PC.
* **Standalone Quest** (USB + developer mode): `python -m usg.cli adb-reverse`, then open `http://localhost:7860/player/#/play?pkg=…` (the exact link is shown under *Using a headset?*).

### The model: started for you from your LM Studio files
`python -m usg.cli app` looks in `~/.lmstudio/models` (override with `LMSTUDIO_HOME`), lists every downloaded GGUF in the dropdown, and starts LM Studio's own
bundled llama.cpp engine on `127.0.0.1:8089` for the preferred model (a Qwen3.5-4B if present). It dies with the app, even if the app is hard-killed.

| engine | used for |
|---|---|
| **Vulkan** (default, `--backend auto`) | AMD / Intel iGPUs, and NVIDIA too |
| **CUDA** (`--backend cuda`) | NVIDIA eGPU |
| **CPU** (`--backend cpu`) | fallback |

```bash
python -m usg.cli app --model qwen2.5-coder --ctx 16384      # pick another downloaded model
python -m usg.cli app --no-llm                               # UI only
```
Measured on an AMD Radeon iGPU (Vulkan), Qwen3.5-4B Q4_K_M: loads in ~6 s, ~14 tokens/s, ~170 tokens/s prompt reading; a scenario takes ~20-80 s.
*External server* (Ollama, LM Studio server, any `llama-server`) is also supported. If a vision projector (`mmproj-*.gguf`) sits next to the GGUF (Qwen3.5 does), tick *map image* in the Generate tab to attach an annotated top-down map to the prompt (the server is restarted with `--mmproj`). `USG_LLAMA_SERVER` selects a different binary.

## The 7 scenario types

| id | task | success / failure |
|---|---|---|
| `ptp_env` | reach a target on sidewalks/paths | target reached / timeout |
| `ptp_road` | reach a target on the road surface | target reached / timeout |
| `cpath` | stay inside a corridor around a path | arrive / leave the corridor, timeout |
| `env_con` | avoid static obstacles (parked cars) | arrive / collision, timeout |
| `dyn_nav` | avoid moving vehicles/walkers | arrive / collision, timeout |
| `dep_comp` | tasks that must be done in order | group success / any required failure |
| `indep_comp` | tasks in any order, concurrently | group success / any required failure |

Each has a map-adaptive reference script in `src/usg/scenarios/` (also the agent's starting point) and rules in `src/usg/scenario_types.py`.

**The same types as constraint axes.** Every task is "reach a target" plus constraints. The 7 types are named points on these axes, and a real
scenario can combine several (e.g. crossing a road with a moving car while obeying the signal). `axes_of(spec, map)` infers the axes of any
generated scenario and the result panel shows them.

| axis | values | named point |
|---|---|---|
| surface | walkable / road / crossing | `ptp_env` (base) / `ptp_road` |
| path | free / corridor | `cpath` |
| static | none / obstacles | `env_con` |
| dynamic | none / movers | `dyn_nav` |
| signal | none / obeyed | (no named type: it is a failure condition) |
| composition | single / ordered / unordered | `dep_comp` / `indep_comp` |

## The task specification language (the core of the method)

A task is **one primitive, "reach a target", plus constraints**, written as data:

```json
{"tasks": [{"name": "wait_then_cross", "instruction": "Wait for green, then cross.",
  "goal":   {"op": "then", "args": [
              {"op": "call", "name": "wait_for_green", "args": {"zone": {"kind": "crossing_side", "id": "crossing_1", "side": "start", "r": 3}, "signal": "signal_1"}},
              {"op": "call", "name": "cross",          "args": {"far_zone": {"kind": "crossing_side", "id": "crossing_1", "side": "end", "r": 2}}}]},
  "safety": [{"op": "call", "name": "obey_signal",    "args": {"zone": {"kind": "crossing", "id": "crossing_1"}, "signal": "signal_1"}}],
  "timeout": {"initial": 70, "baseline": 110}}]}
```
* **atoms** (each returns a signed margin): `in_zone`, `on_surface`, `near_path`, `dist_le/ge`, `look_at`, `speed_le/ge`, `signal_is`, `event`;
* **combinators**: `not and or implies eventually always until then prev`, with time windows in seconds from the task start;
* **definitions**: a standard library (`reach wait_for_green look follow keep_clear pace cross collision_free stay_on obey_signal …`) and, at level 2, definitions the model writes itself.

The goal makes a task *succeed*, a violated safety rule makes it *fail*. The player monitors the formulas on the participant's real pose and reports margins
(metres, degrees, m/s). The 7 scenario types are named points on constraint axes; a scenario's axes are derived from its formulas (`usg.spec.axes`).
Pipelines: **L0** script + task helpers · **L1** specification from the library + world script · **L2** L1 + the model's own definitions (default in the app).
Details: `docs/ARCHITECTURE.md`. A complete walkthrough with a worked example is in `../paper/METHOD.md`.

## The DSL (extension of scenariogeneration)

```python
from usg.dsl import *          # also exports the full `xosc` module: anything scenariogeneration can do still works

cr = MAP.crossings(control="zebra")[0]
scenario = ScenarioBuilder("dyn_nav_car", MAP, scenario_type="dyn_nav")
scenario.user(MAP.crossing_side(cr["id"], "start"))
task = scenario.cross(cr["id"], "start", "Check the traffic, then cross", avoid=["Car1"], timeout=60)
route = MAP.drive_route(cr["road"], 0, 60, "forward")
scenario.vehicle("Car1", route[0], route[1:], speed=8, start_when=when_task_starts(task))
```
`ScenarioBuilder` assembles Event → Maneuver → ManeuverGroup → Act → Story → Storyboard deterministically; the model supplies content only. Pedestrian tasks
(`go_to`, `cross`, `follow_path`; failures for timeout, collision, surface adherence, corridor, signal violation) travel as real `<VRTask>` elements inside a standard
`UserDefinedAction/CustomCommandAction`, so the file stays valid OpenSCENARIO and other tools ignore them. *Initial timeout* = on-time limit (a hint is raised),
*baseline timeout* = hard limit (the task fails).

## Developing the player
The built player is committed inside the package (`src/usg/player_dist`), so Node is not needed to run the app. To change it:
```bash
cd player && npm install
npm run dev                         # vite dev server
npm test                            # TypeScript runtime vs Python ground truth + task rules
npm run build                       # writes ../src/usg/player_dist
python ../scripts/make_player_fixtures.py   # regenerate test fixtures after Python-side changes
```

## Tests
```bash
python -m pytest                    # map, XODR, 7 archetypes, validator, sandbox/security, specification language, agent loop (3 levels), LLM client, local model, Gradio + server routes
cd player && npm test               # surface classifier == Python on 13,440 points, monitor == Python reference on 160 random formulas, OpenSCENARIO parsing, task rules
python scripts/make_player_fixtures.py        # regenerate the player's test fixtures after Python-side changes
python scripts/benchmark.py --reps 3          # the quantitative evaluation (needs the local model); python scripts/summarize_benchmark.py for the tables
```
The TypeScript tests use a **test-only** scripted walker to exercise the rules; the product never moves the player.

## Layout
```
src/usg/    geo, mapmodel, osm, pedgraph, xodr, dsl/, spec/ (formula, monitor, axes, document, oracle), validate, sandbox, tools, scenario_types, scenarios/, storyboard
            llm, localllm (LM Studio engine launcher), agent/ (loop + prompts), render (static plots), app (Gradio + server), cli
src/usg/player_dist/   built three.js player (served at /player)
player/     React + three.js + @react-three/xr source of the player (runtime/, scene/, tests/)
docs/       SECURITY.md, ARCHITECTURE.md
```

## Known limits
* **VR on hardware is untested.** The player loads, runs the scenario and renders in a desktop browser (verified); entering an actual headset session, controller locomotion
  and the in-VR text HUD are written against the library docs but have not been tried on a headset. The VR HUD fetches its font from a CDN on first use.
* Props are procedural placeholders (benches, bus stops, lamps, trees, signals). Drop glTF files next to the player (`assets/manifest.json`) to replace them.
* The **nominal walker** that checks satisfiability is an idealised participant (it yields to traffic, waits for green, keeps its gaze on look targets); a warning means "check the specification", not "impossible".
* `look_at` uses the camera yaw: head orientation in VR, mouse look on the desktop. Eye tracking is not used.
* **Map quality depends on OSM tags** (sidewalks are assumed on residential/secondary roads when untagged); check the map plot before generating.
* Small models adapt reference scripts well but follow nuanced prompts only partly; the validator is the quality gate.
* **OpenDRIVE** export is structurally verified (links, geometry continuity), not validated against esmini or the XSD.
