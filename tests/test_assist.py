"""Deterministic safety nets, tolerant map API, esmini gate and the standard-conform signal export."""
import json
import re
import xml.etree.ElementTree as ET

import pytest

from usg import esmini as esm
from usg import osm, synth, xodr
from usg.agent.loop import run_agent
from usg.dsl import MapQuery
from usg.llm import LLMError
from usg.sandbox import run_script
from usg.signals import lamp_state, signal_numbers, symbolic_state
from usg.tools import ToolServer


class Fake:
    """A scripted chat model: returns the next reply (or raises it if it is an exception)."""
    context_tokens = 24000

    def __init__(self, replies):
        self.replies, self.i = list(replies), 0

    def chat(self, messages, max_tokens=1800, on_token=None):
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        if isinstance(r, Exception):
            raise r
        return r


def server(level=2, assist="off"):
    t = ToolServer(level=level)
    t.load_osm(synth.synthetic_osm())
    t.assist = assist
    return t


def events(t, replies, prompt="Walk to the bus stop."):
    return list(run_agent(Fake(replies), t, prompt, max_steps=8))


def signal_doc(q):
    cr = q.crossings(control="signals")[0]
    sig = cr["signal_id"] or f"{cr['id']}_ped"
    near = {"kind": "crossing_side", "id": cr["id"], "side": "start", "r": 3}
    far = {"kind": "crossing_side", "id": cr["id"], "side": "end", "r": 2}
    return {"tasks": [{"name": "cross_on_green", "instruction": "Wait for green, then cross.",
                       "goal": {"op": "then", "args": [{"op": "call", "name": "wait_for_green", "args": {"zone": near, "signal": sig}},
                                                       {"op": "call", "name": "cross", "args": {"far_zone": far}}]},
                       "safety": [{"op": "call", "name": "obey_signal", "args": {"zone": {"kind": "crossing", "id": cr["id"]}, "signal": sig}},
                                  {"op": "call", "name": "collision_free", "args": {"entity": "Car1", "r": 0.3}}],
                       "timeout": {"initial": 90, "baseline": 140}}]}


# ------------------------------------------------------------------ the nets
def test_world_script_is_written_from_an_accepted_specification():
    t = server()
    r = t.call("submit_spec", {"spec": signal_doc(t.q)})
    assert r["accepted"], r["feedback"]
    assert not t.assist_world().get("accepted") is False
    res = t.result
    assert res["tier"] == "assisted"
    names = {e["name"] for e in res["spec"]["entities"]}
    assert "Car1" in names and res["spec"]["signals"]


def test_fallback_always_gives_a_valid_scenario_even_if_it_does_not_match_the_request():
    t = server(assist="fallback")
    t.prompt = "Wait for the light to turn green, look at the car, then cross."
    r = t.assist_fallback()
    assert r["accepted"] and t.result["tier"] == "fallback" and t.result["fallback_type"] in ("ptp_env", "ptp_road", "cpath", "env_con", "dyn_nav", "dep_comp", "indep_comp")


def test_loop_without_nets_fails_and_with_nets_returns_a_tiered_result():
    ev = events(server(assist="off"), ["I think the answer is yes."] * 6)
    assert ev[-1]["kind"] == "failed" and ev[-1]["reason"] == "model stopped calling tools"
    t = server(assist="fallback")
    ev = events(t, ["I think the answer is yes."] * 6)
    assert ev[-1]["kind"] == "done" and ev[-1]["tier"] == "fallback" and t.result["tier"] == "fallback"


def test_model_errors_are_retried_then_rescued():
    t = server(assist="fallback")
    ev = events(t, [LLMError("server returned 400: request exceeds the context")] * 4)
    assert ev[-1]["kind"] == "done" and ev[-1]["tier"] == "fallback"
    assert sum(e["kind"] == "warning" for e in ev) >= 2                 # the first error is retried with a shorter history, the second rescued


def test_accepted_specification_with_broken_scripts_is_finished_by_the_world_script():
    t = server(assist="fallback")
    spec = f'<tool name="submit_spec">{json.dumps({"spec": signal_doc(t.q)})}</tool>'
    bad = '<tool name="submit_script">```python\nscenario = 1\n```</tool>'
    ev = events(t, [spec] + [bad] * 8, prompt="Wait for the pedestrian light to turn green, then cross the road while a car drives by.")
    assert ev[-1]["kind"] == "done" and ev[-1]["tier"] == "assisted"
    assert t.result["spec"]["tasks"][0]["name"] == "cross_on_green"      # the task rules are still the model's


def test_a_model_success_is_tiered_model():
    t = server(level=0)
    from usg.scenario_types import ARCHETYPES
    t.prompt = "Walk to the bus stop."
    assert t.call("submit_script", {"code": ARCHETYPES["ptp_env"]["template"]})["accepted"]
    assert t.result["tier"] == "model"


# ------------------------------------------------------------------ tolerant map API
def test_map_api_accepts_dicts_pairs_and_ids_where_a_place_or_id_is_expected(tmp_path):
    m = osm.build_map(synth.synthetic_osm())
    mp = tmp_path / "scene_map.json"
    m.save(mp)
    code = """from usg.dsl import *
cr = MAP.crossings()[0]
road = MAP.roads()[0]
a = MAP.crossing_side(cr, 'start', inset=2.0)
b = MAP.crossing_side(cr['id'], 'end', inset=2.0)
assert MAP.surface(cr) in ('crosswalk', 'road', 'sidewalk')
assert MAP.route(cr, [0.0, 0.0]) is not None
assert MAP.dist(cr, road['start']) > 0
s = MAP.sidewalk_at(road, 'right', 10.0)
scenario = ScenarioBuilder('tolerant', MAP, scenario_type='custom')
scenario.user(a)
scenario.go_to(b, 'Walk across', name='x', timeout=60)
"""
    r = run_script(code, mp)
    assert r.ok, r.error


# ------------------------------------------------------------------ esmini gate
def test_esmini_gate_rejects_a_scenario_that_the_standard_player_rejects(monkeypatch, tmp_path):
    from usg.scenario_types import ARCHETYPES
    t = server(level=0)
    t.prompt = "Walk to the bus stop."
    t.esmini = tmp_path / "esmini"
    monkeypatch.setattr(esm, "run", lambda *a, **k: {"rc": 255, "loaded": False, "errors": ["[error] Exception: stoi"], "warnings": []})
    r = t.call("submit_script", {"code": ARCHETYPES["ptp_env"]["template"]})
    assert not r["accepted"] and "standard player" in r["feedback"] and "stoi" in r["feedback"] and t.result is None
    monkeypatch.setattr(esm, "run", lambda *a, **k: {"rc": 0, "loaded": True, "errors": [], "warnings": []})
    assert t.call("submit_script", {"code": ARCHETYPES["ptp_env"]["template"]})["accepted"]


# ------------------------------------------------------------------ standard-conform signal export
def test_signal_ids_are_numeric_and_states_are_lamp_strings():
    m = osm.build_map(synth.synthetic_osm())
    nums = signal_numbers(m, ["crossing_9_ped"])
    assert sorted(nums.values()) == list(range(1, len(nums) + 1)) and nums["crossing_9_ped"] == len(m.signals) + 1
    assert lamp_state("pedestrian", "red") == "on;off" and lamp_state("vehicle", "green") == "off;off;on"
    assert [symbolic_state(x) for x in ("red", "green", "on;off", "off;on", "on;off;off", "off;off;on")] == ["red", "green", "red", "green", "red", "green"]


def test_exported_signals_are_standard_conform(tmp_path):
    t = server(level=0)
    q = t.q
    cr = q.crossings(control="signals")[0]
    code = f"""from usg.dsl import *
scenario = ScenarioBuilder('s', MAP, scenario_type='custom')
scenario.user(MAP.crossing_side({cr['id']!r}, 'start', inset=2.0))
scenario.signal_cycle({cr['id']!r}, green=12, red=15, initial='red')
scenario.cross({cr['id']!r}, 'start', 'Cross when green', name='c', timeout=90)
"""
    res = run_script(code, t.map_path)
    assert res.ok, res.error
    root = ET.fromstring(res.xosc)
    states = [(a.get("name"), a.get("state")) for a in root.iter("TrafficSignalStateAction")]
    assert states and all(n.isdigit() and st in ("on;off", "off;on") for n, st in states)
    decl = {p.get("name"): p.get("value") for p in root.iter("ParameterDeclaration")}
    sig = cr["signal_id"] or f"{cr['id']}_ped"
    assert decl[sig] == states[0][0]                                    # the symbolic name maps to the numeric id
    xodr.export_xodr(t.model, tmp_path / "m.xodr", virtual=[(v["signal"], v["crossing"]) for v in res.spec["virtual_signals"]])
    for e in ET.parse(tmp_path / "m.xodr").getroot().iter("signal"):
        assert e.get("id").isdigit() and e.get("value") is None


def test_a_signal_on_a_crossing_without_a_light_is_exported_with_the_scenario(tmp_path):
    t = server(level=0)
    zebra = t.q.crossings(control="zebra")[0]
    code = f"""from usg.dsl import *
scenario = ScenarioBuilder('s', MAP, scenario_type='custom')
scenario.user(MAP.crossing_side({zebra['id']!r}, 'start', inset=2.0))
scenario.signal_cycle({zebra['id']!r}, green=12, red=15, initial='red')
scenario.cross({zebra['id']!r}, 'start', 'Cross', name='c', timeout=90)
"""
    res = run_script(code, t.map_path)
    assert res.ok, res.error
    virtual = [(v["signal"], v["crossing"]) for v in res.spec["virtual_signals"]]
    assert virtual == [(f"{zebra['id']}_ped", zebra["id"])]
    xodr.export_xodr(t.model, tmp_path / "m.xodr", virtual=virtual)
    sigs = [e.get("name") for e in ET.parse(tmp_path / "m.xodr").getroot().iter("signal")]
    assert f"{zebra['id']}_ped" in sigs
    xodr.export_xodr(t.model, tmp_path / "plain.xodr")                  # without the scenario the map has no such signal
    assert f"{zebra['id']}_ped" not in [e.get("name") for e in ET.parse(tmp_path / "plain.xodr").getroot().iter("signal")]


# ------------------------------------------------------------------ unknown signals are an error the model can fix, not a silent invention
def test_signal_cycle_rejects_ids_the_map_does_not_have(tmp_path):
    t = server(level=0)
    code = """from usg.dsl import *
scenario = ScenarioBuilder('s', MAP, scenario_type='custom')
scenario.user(MAP.crossing_side(MAP.crossings()[0]['id'], 'start', inset=2.0))
scenario.signal_cycle('signal_999', green=10, red=10)
"""
    res = run_script(code, t.map_path)
    assert not res.ok and "neither a crossing id nor a signal id" in (res.error or "")


def test_world_script_refuses_a_specification_that_needs_a_signal_the_map_lacks():
    from usg.assist import world_script
    t = server()
    doc = signal_doc(t.q)
    needs = {"entities": {}, "signals": ["signal_999"], "events": []}
    assert world_script(doc, needs, t.q) is None
    assert "signal_cycle" in world_script(doc, {"entities": {}, "signals": [t.q.crossings(control="signals")[0]["signal_id"]], "events": []}, t.q)
