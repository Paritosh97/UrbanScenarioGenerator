"""Reference policies for ``usg.env.PedestrianTaskEnv``: a lower bound, a map-blind heuristic and a scripted upper bound.

* ``RandomPolicy``    uniform random actions (lower bound).
* ``StraightPolicy``  walks straight at the next goal zone using only the observation (``goal`` block); ignores roads, lights and traffic.
* ``RoutePolicy``     the closed-loop version of the nominal walker (``spec.oracle``): follows the pedestrian route through the goal zones,
  waits for green at gated crossings, yields to approaching traffic, dwells where the formula asks and keeps its gaze on look targets.
  It reads the environment's internals (map, movers), so it is a scripted upper bound for the benchmark, not a learning baseline.
"""
from __future__ import annotations

import math

import numpy as np

from . import geo
from .spec.monitor import dist_to_obb
from .spec.oracle import WALK, _gates, _in_rect, _keep_clear, _legs, _plan, signal_state


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


class RandomPolicy:
    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)

    def reset(self, env=None) -> None:
        pass

    def act(self, obs, env=None):
        return np.array([self.rng.uniform(0.0, 1.0), self.rng.uniform(-1.0, 1.0), 0.0], np.float32)


class StraightPolicy:
    def __init__(self, env):
        self.max_turn, self.dt = env.max_turn, env.dt

    def reset(self, env=None) -> None:
        pass

    def act(self, obs, env=None):
        present, gx, gy, dist = obs["goal"]
        if not present:
            return np.zeros(3, np.float32)
        err = math.atan2(gy, gx)
        turn = float(np.clip(err / (self.max_turn * self.dt), -1.0, 1.0))
        speed = 0.0 if dist < 0.005 else (1.0 if abs(err) < 0.5 else 0.2)
        return np.array([speed, turn, 0.0], np.float32)


class RoutePolicy:
    """Privileged scripted walker; see the module docstring."""

    def __init__(self, env):
        self.env = env
        self._task = None

    def reset(self, env=None) -> None:
        self._task = None

    # ---- per-task plan, rebuilt when the task changes
    def _prepare(self) -> None:
        env = self.env
        t = env.tasks[env.k]
        self._task = t["id"]
        self.stages, self.looks = _plan(t["goal"])
        self.gates = _gates(t["safety"])
        self.yields = _keep_clear(t["safety"], env.movers)
        self.legs: list[tuple] = []
        self.stage_i = 0
        self.dwell = 0.0
        self._lay_legs((env.x, env.y))

    def _lay_legs(self, p) -> None:
        if self.stage_i < len(self.stages):
            self.legs = _legs(self.env.model, p, self.stages[self.stage_i]["c"])[1:]

    def _look_gaze(self, p, heading):
        if not self.looks:
            return 0.0
        kind, v = self.looks[0]
        env = self.env
        if kind == "point":
            tgt = v
        else:
            m = env.movers.get(v)
            if m is None:
                return 0.0
            q = m.at(env.clock)
            tgt = (q[0], q[1])
        return float(np.clip(_wrap(geo.heading(p, tgt) - heading) / (math.pi / 2), -1.0, 1.0))

    def _too_close(self, pt) -> bool:
        env = self.env
        for name, d in self.yields:
            for ahead in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0):          # look 5 s ahead: crossing a lane takes a few seconds
                e = env.movers[name].at(env.clock + ahead)
                if dist_to_obb(pt, (e[0], e[1]), e[2], e[3], e[4]) < d + 0.8:
                    return True
        return False

    def act(self, obs, env=None):
        env = self.env
        if self._task != env.tasks[env.k]["id"]:
            self._prepare()
        p, h = (env.x, env.y), env.heading
        gaze = self._look_gaze(p, h)
        if self.stage_i >= len(self.stages):
            return np.array([0.0, 0.0, gaze], np.float32)
        st = self.stages[self.stage_i]
        # advance along the route
        while self.legs and geo.dist(p, self.legs[0]) < 0.35:
            self.legs.pop(0)
        if not self.legs:                                           # at the stage centre: dwell / wait, then the next stage
            cond = st["wait"]
            waiting = cond and cond[0] in env.cycles and signal_state(env.cycles[cond[0]], env.clock) != cond[1]
            if self.dwell < st["dwell"] or waiting:
                self.dwell += env.dt
                return np.array([0.0, 0.0, gaze], np.float32)
            self.stage_i += 1
            self.dwell = 0.0
            self._lay_legs(p)
            if not self.legs:
                return np.array([0.0, 0.0, gaze], np.float32)
        q = self.legs[0]
        want = geo.heading(p, q)
        err = _wrap(want - h)
        turn = float(np.clip(err / (env.max_turn * env.dt), -1.0, 1.0))
        speed = (WALK / env.max_speed) if abs(err) < 0.5 else 0.15
        nxt = (p[0] + math.cos(want) * WALK * env.dt, p[1] + math.sin(want) * WALK * env.dt)
        for z, s in self.gates:                                     # do not enter a gated crossing on red
            if s in env.cycles and not _in_rect(p, z) and _in_rect(nxt, z) and signal_state(env.cycles[s], env.clock) != "green":
                speed = 0.0
        # a polite pedestrian yields before stepping onto the carriageway, but never freezes in the lane it is already crossing
        if self.yields and env.samples[-1].surface != "road" and self._too_close(nxt):
            speed = 0.0
        return np.array([speed, turn, gaze], np.float32)


def rollout(env, policy, seed: int = 0, max_steps: int = 20000) -> dict:
    """Play one episode; returns success, return, steps, the per-task outcomes and the cost."""
    obs, info = env.reset(seed=seed)
    policy.reset(env)
    cost, steps = 0.0, 0
    for steps in range(1, max_steps + 1):
        obs, r, terminated, truncated, info = env.step(policy.act(obs, env))
        cost += info["cost"]
        if terminated or truncated:
            break
    return {"success": bool(info["success"]), "return": round(info["return"], 3), "steps": steps, "cost": cost,
            "outcomes": info["outcomes"], "reason": next((o.get("reason") for o in info["outcomes"] if o["status"] == "failed"), "")}
