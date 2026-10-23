"""Hard checks that a request fits the map, and the map-area picker's server side."""
import json

import gradio as gr
import pytest

from usg import app, grounding, synth
from usg.agent.loop import run_agent
from usg.dsl import MapQuery
from usg.tools import ToolServer


class Scripted:
    context_tokens = 16000

    def __init__(self, replies):
        self.replies, self.i, self.seen = replies, 0, []

    def chat(self, messages, max_tokens=1800, on_token=None):
        self.seen.append(messages)
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        return r


def _tools(level=2, drop=()):
    t = ToolServer(level=level)
    t.load_osm(synth.synthetic_osm())
    if drop:
        t.model.props = [p for p in t.model.props if p.ptype not in drop]
        t.q = MapQuery(t.model)
    return t


def test_requested_objects_are_recognised_from_natural_phrasing():
    assert grounding.requested_objects("Walk to the trash can, then sit on the bench.") == ["waste_basket", "bench"]
    assert grounding.requested_objects("Cross when the pedestrian light is green") == ["signal_crossing"]
    assert grounding.requested_objects("Go to the bus stop by the lamp post") == ["street_lamp", "bus_stop"]
    assert grounding.requested_objects("Walk along the street") == []


def test_a_request_for_an_object_the_map_lacks_is_refused_before_the_model_runs():
    t = _tools(drop=("waste_basket",))
    llm = Scripted(["should never be called"])
    events = list(run_agent(llm, t, "Walk to the waste basket.", 8))
    assert events[-1]["kind"] == "failed" and "no waste basket" in events[-1]["reason"]
    assert "NOT on this map" in events[-1]["reason"] or "Objects on this map" in events[-1]["reason"]
    assert llm.seen == []                                          # no model call at all


def test_a_signalised_crossing_is_required_for_wait_for_green():
    t = _tools()
    t.model.crossings = [c for c in t.model.crossings if c.control != "signals"]
    t.q = MapQuery(t.model)
    r = grounding.refusal_text("Wait for the green light and cross.", t.q)
    assert r and "signalised crossing" in r


def test_missing_crossing_is_reported_for_a_cross_request():
    t = _tools()
    t.model.crossings = []
    t.q = MapQuery(t.model)
    assert "crossing" in grounding.missing_objects("Cross the road.", t.q)


def test_the_first_message_lists_what_the_map_contains():
    t = _tools()
    llm = Scripted(["Nothing."])
    list(run_agent(llm, t, "Walk to the bench.", 1))
    first = llm.seen[0][1]["content"]
    assert "Objects on this map:" in first and "bench x" in first


def test_a_spec_that_ignores_the_requested_object_is_rejected_with_the_nearest_ids():
    t = _tools()
    t.prompt = "Walk to the bench."
    spec = {"tasks": [{"name": "walk", "instruction": "Walk to the spot.", "timeout": {"initial": 60, "baseline": 90},
                       "goal": {"op": "call", "name": "reach", "args": {"zone": {"kind": "disc", "x": 100.0, "y": 4.5, "r": 2}}}}]}
    r = t.call("submit_spec", spec)
    assert r["ok"] and not r["accepted"] and "bench" in r["feedback"] and "feature" in r["feedback"]
    bench = t.q.props("bench")[0]
    spec["tasks"][0]["goal"]["args"]["zone"] = {"kind": "feature", "id": bench["id"], "r": 3}
    assert t.call("submit_spec", spec)["accepted"]


def test_a_script_that_ignores_the_requested_object_is_rejected_at_level_zero():
    t = _tools(level=0)
    t.prompt = "Walk to the bench."
    code = '''from usg.dsl import *
scenario = ScenarioBuilder("x", MAP, scenario_type="ptp_env")
scenario.user(MAP.crossing_side("crossing_1", "start", 2.0))
scenario.go_to(MAP.crossing_side("crossing_1", "end", 1.0), "Walk to the other side", timeout=120)
'''
    r = t.call("submit_script", {"code": code})
    assert not r["accepted"] and "request not honoured" in r["feedback"]


def test_requests_without_object_words_are_not_constrained():
    t = _tools()
    t.prompt = "Cross at the zebra crossing while a car approaches."
    assert grounding.grounding_errors(t.prompt, t.q, [(0.0, 0.0)]) == [] or "zebra" in grounding.grounding_errors(t.prompt, t.q, [(0.0, 0.0)])[0]


# ------------------------------------------------------------------ the map-area picker (server side)
@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    app.BBOX.clear()
    c = TestClient(app.create_server(app.build_app()))
    yield c
    app.BBOX.clear()


def test_picker_page_is_served(client):
    r = client.get("/mapselect/")
    assert r.status_code == 200 and "leaflet" in r.text.lower() and "Draw area" in r.text


def test_bbox_roundtrip_validation_and_clear(client):
    assert client.get("/api/bbox").json() == {}
    ok = client.post("/api/bbox", json={"south": 48.136, "west": 11.574, "north": 48.139, "east": 11.578})
    assert ok.status_code == 200 and 0.0 < ok.json()["area_km2"] < 1.0
    assert client.get("/api/bbox").json()["north"] == 48.139
    assert client.post("/api/bbox", json={"south": 48.139, "west": 11.574, "north": 48.136, "east": 11.578}).status_code == 422   # south > north
    assert client.post("/api/bbox", json={"south": "x"}).status_code == 422
    assert client.delete("/api/bbox").json() == {"ok": True} and client.get("/api/bbox").json() == {}


def test_load_selected_needs_an_area_and_enforces_the_size_limit():
    app.BBOX.clear()
    with pytest.raises(gr.Error):
        app.load_selected(None)
    app.BBOX.update(south=48.0, west=11.0, north=48.1, east=11.1)          # ~ 60 km2
    with pytest.raises(gr.Error) as e:
        app.load_selected(None)
    assert "choose at most" in str(e.value)
    assert "too large" in app.bbox_text()
    app.BBOX.clear()


def test_load_selected_builds_the_map_from_the_cached_download(monkeypatch, tmp_path):
    p = tmp_path / "x.osm"
    p.write_text(synth.synthetic_osm(), encoding="utf-8")
    monkeypatch.setattr(app.osm, "fetch_osm", lambda *a, **k: p)
    app.BBOX.update(south=48.136, west=11.574, north=48.139, east=11.578)
    t, status, fig = app.load_selected(None)
    assert "selected area" in status.lower() and t.model is not None
    app.BBOX.clear()


def test_the_generate_tab_has_no_pipeline_or_gpu_controls():
    blocks = app.build_app()
    labels = [str(getattr(b, "label", "") or "") for b in blocks.blocks.values()]
    assert not any("Pipeline" in l or "GPU engine" in l or "Context tokens" in l for l in labels)
    assert any("World script" in l for l in labels) and any("Task specification" in l for l in labels)
    assert not any(getattr(b, "label", None) == "Script (no AI)" for b in blocks.blocks.values())


def test_rebuild_from_edited_editors_runs_without_a_model():
    t, *_ = app.load_sample(None)
    from usg.scenario_types import ARCHETYPES
    fb, t2, md, rows, fig, files, vr, story = app.run_script(ARCHETYPES["dyn_nav"]["template"], t, "")
    assert fb.startswith("OK") and rows


# ------------------------------------------------------------------ the request must be honoured (a real failure case from the UI)
ROAD_PROMPT = "Walk out onto the road and stand on the marked spot just past the crossing."


def _road_spec(zone, safety=None):
    return {"tasks": [{"name": "walk_to_spot", "instruction": "Stand on the marked spot.", "timeout": {"initial": 60, "baseline": 90},
                       "goal": {"op": "call", "name": "reach", "args": {"zone": zone}}, **({"safety": safety} if safety else {})}]}


def test_stand_on_the_road_is_rejected_when_the_goal_is_a_kerb():
    t = _tools()
    t.prompt = ROAD_PROMPT
    cr = t.q.crossings()[0]["id"]
    r = t.call("submit_spec", _road_spec({"kind": "crossing_side", "id": cr, "side": "end", "r": 2}))
    assert r["ok"] and not r["accepted"] and "ON THE ROAD" in r["feedback"]


def test_stand_on_the_road_is_accepted_with_a_goal_on_the_carriageway():
    t = _tools()
    t.prompt = ROAD_PROMPT
    c = t.q.crossings()[0]
    road = t.q.along_road(c["road"], c["road_s"] + 6.0, 0.0)
    assert t.model.surface_at((road.x, road.y)) == "road"
    r = t.call("submit_spec", _road_spec({"kind": "disc", "x": round(road.x, 2), "y": round(road.y, 2), "r": 2}))
    assert r["accepted"], r["feedback"]


def test_a_script_that_replaces_the_accepted_specification_is_rejected():
    t = _tools()
    t.prompt = ""
    cr = t.q.crossings(control="signals")[0]
    good = _road_spec({"kind": "crossing_side", "id": cr["id"], "side": "end", "r": 2})
    assert t.call("submit_spec", good)["accepted"]
    script = f'''from usg.dsl import *
scenario = ScenarioBuilder("x", MAP, scenario_type="custom")
scenario.user(MAP.crossing_side("{cr['id']}", "start", 3.0))
SPEC = {{"tasks": [{{"name": "walk_to_spot", "instruction": "x", "timeout": {{"initial": 60, "baseline": 90}},
  "goal": {{"op": "call", "name": "reach", "args": {{"zone": {{"kind": "disc", "x": 0.0, "y": 0.0, "r": 2}}}}}}}}]}}
handles = scenario.apply_spec(SPEC)
'''
    r = t.call("submit_script", {"code": script})
    assert not r["accepted"] and "spec_modified" in r["feedback"]


def test_a_safety_rule_that_contradicts_the_start_is_an_error():
    t = _tools()
    t.prompt = ""
    c = t.q.crossings(control="signals")[0]
    road = t.q.along_road(c["road"], c["road_s"] + 6.0, 0.0)
    doc = _road_spec({"kind": "disc", "x": round(road.x, 2), "y": round(road.y, 2), "r": 2},
                     [{"op": "call", "name": "stay_on", "args": {"surface": "road"}}])
    assert t.call("submit_spec", doc)["accepted"]
    script = f'''from usg.dsl import *
scenario = ScenarioBuilder("x", MAP, scenario_type="custom")
scenario.user(MAP.crossing_side("{c['id']}", "start", 3.0))
handles = scenario.apply_spec(SPEC)
'''
    r = t.call("submit_script", {"code": script})
    assert not r["accepted"] and "spec_rule_violated_by_nominal" in r["feedback"]


@pytest.mark.parametrize("prompt, atoms, needle", [
    ("Wait for the pedestrian light, then cross.", set(), "signal"),
    ("Look at the approaching car and cross.", {"signal_is"}, "look_at"),
    ("A car approaches; cross without being hit.", set(), "traffic approaching"),
])
def test_explicit_cues_need_matching_operators(prompt, atoms, needle):
    t = _tools()
    errs = grounding.intent_errors(prompt, atoms, [(0.0, 0.0)], t.model)
    assert any(needle in e for e in errs), errs


def test_parked_cars_cue_is_checked_on_the_finished_scenario():
    t = _tools()
    axes = {"dynamic": "none", "static": "none"}
    assert any("parked" in e for e in grounding.intent_errors("Avoid the parked cars.", {"dist_ge"}, [(0, 0)], t.model, axes))
    assert not grounding.intent_errors("Avoid the parked cars.", {"dist_ge"}, [(0, 0)], t.model, {"dynamic": "none", "static": "obstacles"})


def test_the_builtin_example_prompt_still_works_with_its_reference_script():
    t = _tools(level=0)
    t.prompt = ROAD_PROMPT
    from usg.scenario_types import ARCHETYPES
    r = t.call("submit_script", {"code": ARCHETYPES["ptp_road"]["template"]})
    assert r["accepted"], r["feedback"]
