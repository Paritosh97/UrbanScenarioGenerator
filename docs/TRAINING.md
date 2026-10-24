# Interfaces for synthetic agents and training

> **Scope.** The paper's contribution is the human-in-the-loop framework (generation, validation, player). This page documents an *enabling interface*: the same
> scenarios run headless for **synthetic user agents**. The agents shipped here are classical (route planning, path following), which also proves that a generated
> scene is doable. Learned agents (RL / imitation, e.g. for robots, delivery vehicles or wheelchairs) are future work that this interface prepares, not a claim.

The generator produces verified pedestrian guided tasks. This page is for people who want to **run synthetic agents on them, train or benchmark learned agents**: a headless
environment (`usg.env`), reference policies (`usg.baselines`) and a dataset format (`usg.dataset`). Nothing here needs a browser, a headset or an LLM.

```bash
pip install -e ".[rl]"                                # adds gymnasium (optional: the environment also works without it)
python scripts/make_dataset.py --out dataset --variants 4 --test-maps munich grenoble
python scripts/eval_baselines.py --dataset dataset    # route / straight / random policies per split, type and map
```

```python
from usg.dataset import iter_scenarios

for sc in iter_scenarios("dataset", split="train"):
    env = sc.env()                                    # sc.row = index row, sc.spec = specification, sc.model = map
    obs, info = env.reset(seed=0)
    done = False
    while not done:
        action = policy(obs)                          # (speed, turn, gaze)
        obs, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
    print(info["success"], info["return"], info["outcomes"])
```

## What an episode is

A scenario is a list of tasks played one after the other (`depends_on` chains are respected, parallel groups are serialised). Each task has a
**goal** formula and **safety** formulas in the specification language (`docs/ARCHITECTURE.md`). A simulated pedestrian is the ego; vehicles and
walkers follow their scripted routes (they do not react to the ego), traffic lights follow their cycles, buildings and water block the ego.
Time step 0.1 s. The task ends when

| outcome | `terminated` | `truncated` | reward |
|---|---|---|---|
| goal satisfied (the monitor's lower margin is >= 0) | task done; episode done after the last task | | + 1/n_tasks |
| a safety rule is violated (e.g. "crossed on red") | yes | | -1, `info['cost'] = 1` |
| the baseline timeout runs out | | yes (`info['reason'] == 'timeout'`) | -1 |

## Action

`Box(3,)`: `[speed, turn, gaze]` in `[0,1] x [-1,1] x [-1,1]`.

| | meaning | scale |
|---|---|---|
| `speed` | forward speed | x `max_speed` (default 1.8 m/s) |
| `turn` | body turn rate | x `max_turn` (default pi rad/s) |
| `gaze` | head yaw relative to the body | x 90 degrees (only `look_at` atoms read it) |

## Observation

A dict of float32 arrays of **fixed size**; variable-length lists are padded and masked (first column = present flag).

| key | shape | content |
|---|---|---|
| `ego` | (10,) | speed/max_speed, sin and cos of the gaze offset, one-hot surface (crosswalk, sidewalk, path, ground, road, building, water) |
| `goal` | (4,) | present, dx, dy, distance of the next goal zone in the ego frame (/100 m); zeros with `goal_hint=False` |
| `task` | (3,) | task index / n, remaining time fraction, n_tasks / 8 |
| `entities` | (8, 8) | nearest first: present, x, y (ego frame, /50 m), cos and sin of the relative heading, length/10, width/5, is_vehicle |
| `signals` | (8, 3) | per traffic light: present, is_green, seconds to the next switch /60 |

`PedestrianTaskEnv.obs_schema()` returns this table as a dict. `goal` is privileged guidance (the zone centre from the formula); switch it off
with `goal_hint=False` to make the agent find the target from the instruction and the map itself. The text of the current instruction is in
`info['instruction']`. The raw margins of every formula are in `info['goal_margin']` and `info['safety_margins']` as `(lo, hi)` pairs.

## Reward and cost

The reward comes from the **same quantitative monitor the VR player uses** (`spec/monitor.py`; the TypeScript port is tested for parity):

* **progress**: improvement of the best goal margin so far, divided by the absolute initial margin (so the sum over a task is at most 1);
  walking back and forth earns nothing;
* **task success** +1/n_tasks; **failure** -1 (a rule broken or the timeout);
* optional `step_penalty` per second;
* **`info['cost']`** is 1 on the step a safety rule is violated, 0 otherwise, for constrained / safe RL.

Margins are in the unit of the atoms (metres to a zone or an obstacle, degrees of gaze, m/s). Qualitative atoms (`on_surface`, `signal_is`,
`event`) give +-1, so a rule made only of them gives a flat, sparse signal.

## Reference policies (`usg.baselines`)

| policy | what it does |
|---|---|
| `RandomPolicy` | uniform random actions (lower bound) |
| `StraightPolicy` | heads straight for the next goal zone from the observation; ignores streets, lights and traffic |
| `RoutePolicy` | scripted walker: follows the pedestrian route through the goal zones, waits for green, yields to traffic, dwells and looks where the formula asks. It reads the environment internals, so it is an upper bound, not a learning baseline |

`rollout(env, policy, seed)` plays one episode and returns success, return, cost and the per-task outcomes.
Demo results (two areas): `paper/results/env_baselines_demo.md`. On the reference-script scenarios `StraightPolicy` already solves almost as many as `RoutePolicy`
(98% vs 96%); they separate random from goal-directed behaviour, not map-aware from map-blind. Signals, `look_at` and dense traffic need the LLM-generated scenarios.

## Dataset format (`usg.dataset`)

```
dataset/index.jsonl                 one row per scenario: id, map, type, axes, split, source, counts, nominal margins
dataset/STATS.md                    coverage / diversity tables
dataset/maps/<map>/scene_map.json   metric map model        dataset/maps/<map>/map.xodr   the same geometry as OpenDRIVE
dataset/scenarios/<id>.spec.json    entities, signals, tasks with goal / safety formulas
dataset/scenarios/<id>.xosc         OpenSCENARIO with the <VRTask>/<Spec> extension (playable in the VR player)
```

* **Splits are by map** (`--test-maps`), so a model trained on `train` is tested on streets it has never seen.
* **Sources**: `reference` = the seven reference scripts varied by the choice of crossing or landmark (deterministic, no model needed);
  `llm` = accepted scenarios from `scripts/benchmark.py --save-specs`, added with `make_dataset.py --runs`.
* Every scenario passed the map-aware validator and, where it applies, the nominal-walker check (`nominal_ok` in the index).

## Limits (read before you train)

* Other road users are scripted: they do not react to the ego, so the traffic is a time-dependent obstacle field, not an interactive crowd.
* The reference-script scenarios carry no traffic lights and no `look_at` (the helpers cannot express them); those constraints come from the
  LLM-generated scenarios (L1/L2). Check `STATS.md` for the constraint axes your split actually contains.
* The ego is a kinematic point with a body heading and a head yaw; no gait, no physics beyond blocking by buildings and water.
* Props, buildings and the road surface come from OpenStreetMap tags, so quality varies by city.
* The scripted walker succeeding is a check that a scenario is solvable, not a measure of difficulty for a learned agent.
