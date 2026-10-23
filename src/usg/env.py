"""Headless training environment for the generated guided tasks (Gymnasium-style, no VR, no browser).

A generated scenario (the ``spec`` dict produced by the sandbox, ``ScenarioBuilder.to_spec``) plus its ``MapModel`` becomes an episodic
control problem in which a simulated pedestrian is the ego:

* **action**  ``[speed, turn, gaze]`` in ``[0,1] x [-1,1] x [-1,1]``: walking speed as a fraction of ``max_speed``, turn rate as a fraction of
  ``max_turn`` (rad/s), head yaw relative to the body as a fraction of 90 degrees (only the ``look_at`` atoms read the gaze).
* **reward**  dense and unit-free, from the SAME quantitative monitor the player uses (``spec.monitor``): the improvement of the best goal margin
  so far, normalised by the initial margin, plus +1/n_tasks when a task succeeds and -1 when a safety rule or the baseline timeout fails the
  task. ``info['cost']`` is 1 on the step a safety rule is violated, for constrained / safe RL.
* **observation**  a dict of float32 arrays of fixed size (see ``obs_schema``); entity and signal lists are padded and masked, so a
  variable number of vehicles, walkers and lights fits one tensor.

Tasks are played in id order, one after the other (``depends_on`` chains are respected, parallel groups are serialised). Vehicles and walkers
follow their scripted routes (they do not react to the ego), traffic lights follow their cycles, buildings and water block the ego.

No dependency beyond numpy; if ``gymnasium`` is installed the class is a ``gymnasium.Env`` with proper ``spaces``.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

from . import geo
from .spec import formula as F
from .spec.monitor import Sample, goal_status
from .spec.oracle import DT, _plan, build_movers, signal_state

try:                                                     # optional
    import gymnasium as gym
    from gymnasium import spaces
    _Base = gym.Env
except Exception:                                        # pragma: no cover - exercised when gymnasium is missing
    gym = spaces = None
    _Base = object

SURFACES = ("crosswalk", "sidewalk", "path", "ground", "road", "building", "water")
MAX_SIGNALS = 8
EGO_DIM = 3 + len(SURFACES)
GOAL_DIM = 4
TASK_DIM = 3
ENT_DIM = 8
CLIP = 100.0                      # metres: goal margins are clipped to +-CLIP before differencing


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


class PedestrianTaskEnv(_Base):
    metadata = {"render_modes": []}

    def __init__(self, spec: dict, model, *, dt: float = DT, max_speed: float = 1.8, max_turn: float = math.pi,
                 max_entities: int = 8, goal_hint: bool = True, step_penalty: float = 0.0, seed: Optional[int] = None):
        self.spec, self.model = spec, model
        self.dt, self.max_speed, self.max_turn = dt, max_speed, max_turn
        self.max_entities, self.goal_hint, self.step_penalty = max_entities, goal_hint, step_penalty
        self.tasks = sorted((t for t in spec["tasks"] if "goal" in t), key=lambda t: t["id"])
        if not self.tasks:
            raise ValueError("the scenario has no task with a goal formula")
        self.user = next(e for e in spec["entities"] if e["role"] == "user")
        self.cycles = {c["signal"]: c for c in spec["signals"]}
        self.signal_names = sorted(self.cycles)[:MAX_SIGNALS]
        self.entity_names = [e["name"] for e in spec["entities"] if e["role"] != "user"]
        self.roles = {e["name"]: e["role"] for e in spec["entities"]}
        self._rng = np.random.default_rng(seed)
        self.horizon = max(float(t["timeout"]["baseline"]) for t in self.tasks)
        if gym is not None:
            self.action_space = spaces.Box(np.array([0.0, -1.0, -1.0], np.float32), np.array([1.0, 1.0, 1.0], np.float32))
            self.observation_space = spaces.Dict({
                k: spaces.Box(-np.inf, np.inf, shape=s, dtype=np.float32) for k, s in self.obs_shapes().items()})
        self.reset()

    # ------------------------------------------------------------------ schema
    def obs_shapes(self) -> dict[str, tuple]:
        return {"ego": (EGO_DIM,), "goal": (GOAL_DIM,), "task": (TASK_DIM,),
                "entities": (self.max_entities, ENT_DIM), "signals": (MAX_SIGNALS, 3)}

    @staticmethod
    def obs_schema() -> dict[str, str]:
        return {
            "ego": "[speed/max_speed, sin(gaze_offset), cos(gaze_offset)] + one-hot surface under the ego " + str(SURFACES),
            "goal": "[present, dx/100, dy/100, dist/100] of the next goal zone in the ego frame (x forward, y left); zeros when goal_hint=False",
            "task": "[task_index/n_tasks, 1 - task_time/baseline, n_tasks/8]",
            "entities": "(K, 8) nearest first: [present, x/50, y/50 (ego frame), cos, sin (relative heading), length/10, width/5, is_vehicle]",
            "signals": "(8, 3) per traffic light: [present, is_green, seconds_to_switch/60]",
        }

    # ------------------------------------------------------------------ episode
    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self.k = 0                                       # current task index
        self.clock = 0.0                                 # absolute scenario time
        self.times: dict[int, tuple] = {}                # task id -> (start, end) absolute times, end = inf while running
        self.x, self.y, self.heading = self.user["start"]["x"], self.user["start"]["y"], self.user["start"]["h"]
        self.speed = 0.0
        self.gaze_off = 0.0
        self.returns = 0.0
        self.outcomes: list[dict] = []
        self._begin_task()
        return self._obs(), self._info("running", "", self.status)

    def _begin_task(self) -> None:
        t = self.tasks[self.k]
        start = max(float(t["start_time"]), self.clock,
                    *[self.times.get(d, (0.0, 0.0))[1] for d in t["depends_on"]])
        self.clock = start
        self.times[t["id"]] = (start, math.inf)
        self.movers = build_movers(self.spec, starts=self.times)
        self.stages, _ = _plan(t["goal"])
        self.stage_i = 0
        self.t_task = 0.0
        self.samples: list[Sample] = []
        self._snap()
        self.status = self._status()
        self.best = self._clip(self.status["goal"][0])
        self.scale = max(abs(self.best), 1.0)

    # ------------------------------------------------------------------ simulation
    def _events(self, t: dict) -> frozenset:
        names = F.events_in(t["goal"]) | {e for f in t["safety"] for e in F.events_in(f)}
        return frozenset(n for n in names if n.startswith("move_") and n[5:] in self.movers and self.clock >= self.movers[n[5:]].t0)

    def _snap(self, surface: Optional[str] = None) -> None:
        t = self.tasks[self.k]
        ents = {n: self.movers[n].at(self.clock) for n in self.entity_names if n in self.movers}
        sigs = {s: signal_state(c, self.clock) for s, c in self.cycles.items()}
        gaze = self.heading + self.gaze_off
        surface = surface or self.model.surface_at((self.x, self.y))
        self.samples.append(Sample(self.x, self.y, gaze, self.speed, surface, ents, sigs, self._events(t)))

    def _status(self, complete: bool = False) -> dict:
        t = self.tasks[self.k]
        return goal_status(t["goal"], t["safety"], self.samples, self.dt, complete)

    @staticmethod
    def _clip(lo: float) -> float:
        return max(-CLIP, min(CLIP, lo))

    def step(self, action):
        a = np.asarray(action, dtype=np.float64).reshape(-1)
        v = float(np.clip(a[0], 0.0, 1.0)) * self.max_speed
        self.heading = _wrap(self.heading + float(np.clip(a[1], -1.0, 1.0)) * self.max_turn * self.dt)
        self.gaze_off = float(np.clip(a[2], -1.0, 1.0)) * math.pi / 2
        nx, ny = self.x + math.cos(self.heading) * v * self.dt, self.y + math.sin(self.heading) * v * self.dt
        surface = self.model.surface_at((nx, ny))
        blocked = surface in ("building", "water")
        if blocked:
            v, surface = 0.0, None                       # stay where we are; the snapshot re-reads the surface of the old position
        else:
            self.x, self.y = nx, ny
        self.speed = v
        self.clock += self.dt
        self.t_task += self.dt
        self._snap(surface)

        t = self.tasks[self.k]
        timeout = self.t_task >= float(t["timeout"]["baseline"]) - 1e-9
        st = self.status = self._status(complete=timeout)
        lo = self._clip(st["goal"][0])
        reward = (max(lo, self.best) - self.best) / self.scale - self.step_penalty * self.dt
        self.best = max(self.best, lo)
        cost = 1.0 if any(hi < 0 for _, hi in st["safety"]) else 0.0
        terminated = truncated = False
        reason = st["reason"]
        if st["status"] == "success":
            reward += 1.0 / len(self.tasks)
            self.outcomes.append({"task": t["id"], "status": "success", "time": round(self.t_task, 2)})
            self.times[t["id"]] = (self.times[t["id"]][0], self.clock)
            if self.k + 1 < len(self.tasks):
                self.k += 1
                self._begin_task()
            else:
                terminated = True
        elif st["status"] == "failed" or timeout:
            reward -= 1.0
            hard = st["status"] == "failed" and not timeout        # a rule was broken before the time ran out
            reason = reason if hard else "timeout"
            self.outcomes.append({"task": t["id"], "status": "failed", "reason": reason, "time": round(self.t_task, 2)})
            terminated, truncated = hard, not hard
        self.returns += reward
        info = self._info(st["status"], reason, st)
        info.update(cost=cost, blocked=blocked)
        return self._obs(), float(reward), terminated, truncated, info

    # ------------------------------------------------------------------ observation / info
    def _to_ego(self, px: float, py: float) -> tuple[float, float]:
        dx, dy = px - self.x, py - self.y
        c, s = math.cos(self.heading), math.sin(self.heading)
        return dx * c + dy * s, -dx * s + dy * c

    def _next_goal(self) -> Optional[tuple]:
        while self.stage_i < len(self.stages) - 1 and geo.dist((self.x, self.y), self.stages[self.stage_i]["c"]) < 1.5:
            self.stage_i += 1
        return self.stages[self.stage_i]["c"] if self.stages else None

    def _obs(self) -> dict[str, np.ndarray]:
        ego = np.zeros(EGO_DIM, np.float32)
        ego[0], ego[1], ego[2] = self.speed / self.max_speed, math.sin(self.gaze_off), math.cos(self.gaze_off)
        surf = self.samples[-1].surface
        ego[3 + (SURFACES.index(surf) if surf in SURFACES else SURFACES.index("ground"))] = 1.0
        goal = np.zeros(GOAL_DIM, np.float32)
        c = self._next_goal() if self.goal_hint else None
        if c is not None:
            gx, gy = self._to_ego(*c)
            goal[:] = (1.0, gx / 100.0, gy / 100.0, math.hypot(gx, gy) / 100.0)
        t = self.tasks[self.k]
        task = np.array([self.k / len(self.tasks), 1.0 - self.t_task / max(float(t["timeout"]["baseline"]), 1e-6),
                         len(self.tasks) / 8.0], np.float32)
        near = []
        for n, e in self.samples[-1].ents.items():
            ex, ey = self._to_ego(e[0], e[1])
            rel = _wrap(e[2] - self.heading)
            near.append((math.hypot(ex, ey), [1.0, ex / 50.0, ey / 50.0, math.cos(rel), math.sin(rel), e[3] / 10.0, e[4] / 5.0,
                                              1.0 if self.roles.get(n) == "vehicle" else 0.0]))
        near.sort(key=lambda p: p[0])
        ents = np.zeros((self.max_entities, ENT_DIM), np.float32)
        for i, (_, row) in enumerate(near[:self.max_entities]):
            ents[i] = row
        sig = np.zeros((MAX_SIGNALS, 3), np.float32)
        for i, name in enumerate(self.signal_names):
            c_ = self.cycles[name]
            state = self.samples[-1].signals[name]
            sig[i] = (1.0, 1.0 if state == "green" else 0.0, self._to_switch(c_) / 60.0)
        return {"ego": ego, "goal": goal, "task": task, "entities": ents, "signals": sig}

    def _to_switch(self, c: dict) -> float:
        state, nxt = c["initial"], c["offset"] + (c["red"] if c["initial"] == "red" else c["green"])
        while self.clock >= nxt and nxt < 1e5:
            state = "green" if state == "red" else "red"
            nxt += c["green"] if state == "green" else c["red"]
        return max(0.0, nxt - self.clock)

    def _info(self, status: str, reason: str, st: dict) -> dict[str, Any]:
        t = self.tasks[self.k]
        return {"task_id": t["id"], "task_name": t.get("name"), "instruction": t.get("instruction"), "status": status, "reason": reason,
                "time": round(self.t_task, 2), "pose": (self.x, self.y, self.heading), "goal_margin": st["goal"],
                "safety_margins": st["safety"], "cost": 0.0, "outcomes": list(self.outcomes), "return": self.returns,
                "success": len(self.outcomes) == len(self.tasks) and all(o["status"] == "success" for o in self.outcomes)}

    def trace(self) -> list[Sample]:
        """The samples of the task being played (what the monitor sees)."""
        return list(self.samples)
