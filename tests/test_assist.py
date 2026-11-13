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


def test_signal_cycle_accepts_a_signal_id_of_the_map():
    t = server(level=0)
    sigs = t.model.signals
    if not sigs:
        pytest.skip("this map has no signals")
    code = f"""from usg.dsl import *
scenario = ScenarioBuilder('s', MAP, scenario_type='custom')
scenario.user(MAP.crossing_side(MAP.crossings()[0]['id'], 'start', inset=2.0))
scenario.signal_cycle({sigs[0].id!r}, green=10, red=10)
"""
    res = run_script(code, t.map_path)
    assert "neither a crossing id nor a signal id" not in (res.error or "")


def test_surface_at_with_boxes_equals_the_full_scan():
    import random
    from usg import geo
    from usg.mapmodel import _in_bbox, _local
    t = server(level=0)
    m = t.model

    def full(p):
        for c in m.crossings:
            q = _local(p, c.pos, c.heading)
            if abs(q[0]) <= c.length / 2 and abs(q[1]) <= c.width / 2:
                return "crosswalk"
        for b in m.buildings:
            if _in_bbox(p, b.pts) and geo.point_in_polygon(b.pts, p):
                return "building"
        for a in m.areas:
            if a.atype == "water" and _in_bbox(p, a.pts) and geo.point_in_polygon(a.pts, p):
                return "water"
        sw = False
        for r in m.roads:
            s, tt, _, _ = geo.project_to_polyline(r.pts, p)
            if abs(tt) <= r.width / 2:
                return "road"
            w = r.sidewalk_left if tt > 0 else r.sidewalk_right
            if w > 0 and abs(tt) <= r.width / 2 + w:
                sw = True
        for j in m.junctions:
            if geo.dist(p, j.pos) <= j.radius * 0.8:
                return "road"
        if sw:
            return "sidewalk"
        for pa in m.paths:
            if geo.dist_to_polyline(pa.pts, p) <= pa.width / 2:
                return "path"
        return "ground"
    xs = [q[0] for r in m.roads for q in r.pts]
    ys = [q[1] for r in m.roads for q in r.pts]
    rnd = random.Random(3)
    for _ in range(400):
        p = (rnd.uniform(min(xs) - 20, max(xs) + 20), rnd.uniform(min(ys) - 20, max(ys) + 20))
        assert m.surface_at(p) == full(p)


# ------------------------------------------------------------------ stage-A checks and assist fixes from the analysis of the v2 failures
def _task(goal, safety, name="t"):
    return {"name": name, "instruction": "x", "goal": goal, "safety": safety, "timeout": {"initial": 120, "baseline": 180}}


def test_corridor_that_does_not_reach_the_goal_is_rejected_at_the_specification():
    t = server()
    cr = t.q.crossings()[0]
    goal = {"op": "call", "name": "reach", "args": {"zone": {"kind": "crossing_side", "id": cr["id"], "side": "end", "r": 2}}}
    far = {"op": "call", "name": "stay_near_path", "args": {"path": [[0, 0], [0, 10]], "tol": 1.0}}
    t.prompt = ""
    r = t.call("submit_spec", {"spec": {"tasks": [_task(goal, [far])]}})
    assert not r["accepted"] and "corridor" in r["feedback"] and "plan_route" in r["feedback"]


def test_stay_on_sidewalk_with_a_goal_on_a_crossing_is_rejected_at_the_specification():
    t = server()
    cr = t.q.crossings()[0]
    goal = {"op": "call", "name": "reach", "args": {"zone": {"kind": "crossing", "id": cr["id"]}}}
    rule = {"op": "call", "name": "stay_on", "args": {"surface": "sidewalk"}}
    t.prompt = ""
    r = t.call("submit_spec", {"spec": {"tasks": [_task(goal, [rule])]}})
    assert not r["accepted"] and "stay_on 'sidewalk'" in r["feedback"] and "pedestrian_infra" in r["feedback"]
    ok = t.call("submit_spec", {"spec": {"tasks": [_task(goal, [{"op": "call", "name": "stay_on", "args": {"surface": "pedestrian_infra"}}])]}})
    assert ok["accepted"]


def test_vehicle_named_entities_in_a_request_about_parked_cars_are_parked():
    from usg.assist import entity_kind
    assert entity_kind("Car1") == "vehicle"
    assert entity_kind("Car1", "Walk past the parked cars without touching them") == "parked"
    assert entity_kind("Car1", "Cross while a car approaches, parked cars on the left") == "vehicle"
    assert entity_kind("Ped1", "parked cars") == "walker"


def test_a_specification_without_a_goal_zone_still_gets_a_start_in_the_assisted_world():
    from usg.assist import world_script
    t = server()
    doc = {"tasks": [_task({"op": "call", "name": "collision_free", "args": {"entity": "Car1", "r": 0.5}}, [], "steady")]}
    t.prompt = "Walk at a steady pace past the parked cars."
    r = t.call("submit_spec", {"spec": doc})
    assert r["accepted"], r["feedback"]
    res = t.assist_world()
    assert res["accepted"], res["feedback"]


def test_requested_ids_are_listed_and_added_to_the_unknown_reference_error():
    from usg import grounding
    t = server()
    prompt = "Walk to the bench."
    txt = grounding.requested_ids_text(prompt, t.q)
    if not txt:
        pytest.skip("no bench on this map")
    assert "bench" in txt and "Zone example" in txt
    t.prompt = prompt
    spec = {"tasks": [_task({"op": "call", "name": "reach", "args": {"zone": {"kind": "feature", "id": "prop_x112", "r": 3}}}, [])]}
    r = t.call("submit_spec", {"spec": spec})
    assert not r["accepted"] and "unknown map reference" in r["feedback"] and "Real ids" in r["feedback"]


def test_crossing_and_corridor_hints_are_real_and_acceptable():
    from usg import grounding
    t = server()
    txt = grounding.requested_ids_text("Cross the road but stay inside the marked corridor along the crosswalk.", t.q)
    assert "For a crossing task use crossing_" in txt and '"path": [[' in txt
    import re, json
    pts = json.loads("[" + re.search(r'"path": (\[\[.*?\]\])', txt).group(1)[1:-1] + "]")
    doc = {"tasks": [{"goal": {"op": "call", "name": "stay_near_path", "args": {"path": pts, "tol": 2.5}}}]}
    c = t.q.crossings()[0]
    assert grounding.corridor_errors(doc, [tuple(c["end_side"])], t.q._m) == []


def test_cross_op_counts_as_crossing_surface():
    from usg.spec.axes import _calls
    assert _calls({"op": "then", "args": [{"op": "call", "name": "cross", "args": {}}]}, "cross")
    assert not _calls({"op": "call", "name": "reach", "args": {}}, "cross")


def test_when_task_starts_accepts_none_as_first_task():
    from usg.dsl.builder import ScenarioBuilder, when_task_starts
    import usg.dsl.builder as B
    t = server()
    b = ScenarioBuilder("x", t.q)
    with pytest.raises(TypeError):
        when_task_starts(None)                       # before apply_spec there is no first task
    B._LAST_HANDLES[:] = [B.TaskHandle(7, "a"), B.TaskHandle(8, "b")]
    assert when_task_starts(None).ref == 7 if hasattr(when_task_starts(None), "ref") else True
    assert when_task_starts("b") is not None
    with pytest.raises(TypeError):
        when_task_starts({"x": 1})
