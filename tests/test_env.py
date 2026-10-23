"""The headless training environment and its reference policies."""
import numpy as np
import pytest

from usg import osm, synth
from usg.baselines import RandomPolicy, RoutePolicy, StraightPolicy, rollout
from usg.env import EGO_DIM, ENT_DIM, GOAL_DIM, MAX_SIGNALS, TASK_DIM, PedestrianTaskEnv
from usg.sandbox import run_script
from usg.scenario_types import ARCHETYPES
from usg.spec.monitor import goal_status


@pytest.fixture(scope="module")
def model():
    return osm.build_map(synth.synthetic_osm())


@pytest.fixture(scope="module")
def specs(model, tmp_path_factory):
    mp = tmp_path_factory.mktemp("envmap") / "scene_map.json"
    model.save(mp)
    out = {}
    for sid, a in ARCHETYPES.items():
        r = run_script(a["template"], mp)
        assert r.ok, (sid, r.error)
        out[sid] = r.spec
    return out


def test_observation_matches_the_schema(specs, model):
    env = PedestrianTaskEnv(specs["dyn_nav"], model)
    obs, info = env.reset(seed=0)
    assert {k: v.shape for k, v in obs.items()} == {"ego": (EGO_DIM,), "goal": (GOAL_DIM,), "task": (TASK_DIM,),
                                                    "entities": (env.max_entities, ENT_DIM), "signals": (MAX_SIGNALS, 3)}
    assert all(v.dtype == np.float32 and np.isfinite(v).all() for v in obs.values())
    assert obs["goal"][0] == 1.0 and obs["entities"][:, 0].sum() >= 1.0      # a goal zone and at least the car
    assert info["task_id"] == env.tasks[0]["id"] and info["status"] == "running"
    assert set(PedestrianTaskEnv.obs_schema()) == set(obs)


def test_gymnasium_spaces_when_available(specs, model):
    gym = pytest.importorskip("gymnasium")
    env = PedestrianTaskEnv(specs["ptp_env"], model)
    obs, _ = env.reset(seed=1)
    assert env.observation_space.contains(obs)
    assert env.action_space.contains(env.action_space.sample())


@pytest.mark.parametrize("sid", sorted(ARCHETYPES))
def test_scripted_walker_solves_every_archetype(sid, specs, model):
    env = PedestrianTaskEnv(specs[sid], model)
    res = rollout(env, RoutePolicy(env))
    assert res["success"], res
    assert res["cost"] == 0.0
    assert res["return"] > 0.9 * len(env.tasks)


@pytest.mark.parametrize("sid", sorted(ARCHETYPES))
def test_final_margins_agree_with_the_monitor(sid, specs, model):
    """The environment decides success with the same monitor the player uses: re-evaluating the last task's trace gives lo >= 0."""
    env = PedestrianTaskEnv(specs[sid], model)
    assert rollout(env, RoutePolicy(env))["success"]
    t = env.tasks[-1]
    st = goal_status(t["goal"], t["safety"], env.trace(), env.dt, complete=False)
    assert st["status"] == "success" and st["goal"][0] >= 0


def test_random_walker_breaks_safety_rules(specs, model):
    env = PedestrianTaskEnv(specs["dyn_nav"], model)
    res = rollout(env, RandomPolicy(0))
    assert not res["success"] and res["cost"] == 1.0 and res["reason"].startswith("safety")


def test_standing_still_times_out_as_truncation(specs, model):
    env = PedestrianTaskEnv(specs["ptp_env"], model)
    env.reset(seed=0)
    for _ in range(int(env.horizon / env.dt) + 5):
        _, r, terminated, truncated, info = env.step([0.0, 0.0, 0.0])
        if terminated or truncated:
            break
    assert truncated and not terminated and info["reason"] == "timeout" and r < 0
    assert not info["success"]


def test_reward_is_dense_and_bounded(specs, model):
    env = PedestrianTaskEnv(specs["ptp_env"], model)
    env.reset(seed=0)
    rewards = []
    pol = StraightPolicy(env)
    obs, _ = env.reset(seed=0)
    for _ in range(2000):
        obs, r, term, trunc, info = env.step(pol.act(obs))
        rewards.append(r)
        if term or trunc:
            break
    progress = [r for r in rewards[:-1]]
    assert sum(1 for r in progress if r > 0) > 5                    # shaping gives a signal before the goal is reached
    assert all(r <= 1.0 + 1e-9 for r in progress) and info["success"]
    assert rewards[-1] <= 2.0 + 1e-9                                 # last step: remaining progress + the task-success bonus
    assert sum(progress) <= 1.0 + 1e-6                              # best-so-far progress is normalised by the initial margin


def test_buildings_block_the_ego(specs, model, monkeypatch):
    env = PedestrianTaskEnv(specs["ptp_env"], model)
    env.reset(seed=0)
    x, y = env.x, env.y
    monkeypatch.setattr(model, "surface_at", lambda p: "building")
    _, _, _, _, info = env.step([1.0, 0.0, 0.0])
    assert info["blocked"] and (env.x, env.y) == (x, y)


def test_rollouts_are_deterministic(specs, model):
    a = rollout(PedestrianTaskEnv(specs["dyn_nav"], model), RandomPolicy(3))
    b = rollout(PedestrianTaskEnv(specs["dyn_nav"], model), RandomPolicy(3))
    assert a == b
