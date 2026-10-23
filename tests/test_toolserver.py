import json

from usg import synth
from usg.scenario_types import ARCHETYPES
from usg.tools import ToolServer, system_prompt, tool_specs


def make():
    ts = ToolServer()
    ts.load_osm(synth.synthetic_osm())
    return ts


def test_tools_ground_the_agent():
    ts = make()
    ov = ts.call("get_map_overview")
    assert ov["ok"] and "crossing_3" in ov["zebra_crossings"]
    r = ts.call("list_features", {"kind": "crossing", "near": [0, 0], "radius": 30})
    assert {i["id"] for i in r["items"]} == {"crossing_1", "crossing_2", "crossing_4", "crossing_5"}
    assert ts.call("check_point", {"x": -5, "y": 4.2})["surface"] == "sidewalk"
    rt = ts.call("plan_route", {"from": [20, 4.5], "to": [20, -4.5]})
    assert rt["crossings"] == ["crossing_1"]
    assert ts.call("get_feature", {"id": "nope"})["ok"] is False
    assert ts.call("bogus")["ok"] is False


def test_agent_repair_loop_with_scripted_llm():
    """A first bad script is rejected with actionable text; the fixed one is accepted and packaged."""
    ts = make()
    bad = ARCHETYPES["dyn_nav"]["template"].replace('speed=8.0', 'speed=0.0')
    r1 = ts.call("submit_script", {"code": bad})
    assert not r1["accepted"] and "vehicle_speed" in r1["feedback"]
    r2 = ts.call("submit_script", {"code": ARCHETYPES["dyn_nav"]["template"]})
    assert r2["accepted"]
    pkg = json.loads(ts.final_package("t"))
    assert pkg["format"] == "usg-scenario-package/1" and "<OpenSCENARIO" in pkg["xosc"]
    assert pkg["map"]["crossings"] and pkg["spec"]["tasks"]
    assert ts.attempts == 2


def test_policy_violation_is_reported_not_raised():
    r = make().call("submit_script", {"code": "import os\n"})
    assert not r["accepted"] and "not allowed" in r["feedback"]


def test_system_prompt_is_complete():
    p = system_prompt()
    assert "{{" not in p and all(t["name"] in p for t in tool_specs()) and "ScenarioBuilder" in p
    assert len(p) < 14000          # fits comfortably in a small model's context


def test_cli_roundtrip(tmp_path):
    from usg.cli import main
    from usg.scenario_types import ARCHETYPES
    assert main(["sample", "--out", str(tmp_path)]) == 0
    script = tmp_path / "s.py"
    script.write_text(ARCHETYPES["dep_comp"]["template"], encoding="utf-8")
    pkg = tmp_path / "p.usgscene.json"
    assert main(["check", str(script), "--map", str(tmp_path / "scene_map.json"), "--package", str(pkg)]) == 0
    assert json.loads(pkg.read_text(encoding="utf-8"))["spec"]["scenario_type"] == "dep_comp"
    bad = tmp_path / "bad.py"
    bad.write_text("import os\n", encoding="utf-8")
    assert main(["check", str(bad), "--map", str(tmp_path / "scene_map.json")]) == 1


# ------------------------------------------------------------------ lenient arguments (found with a real Qwen3.5-4B run)
def test_tools_accept_the_argument_shapes_small_models_send():
    ts = make()
    shapes = [{"kind": "crossing", "near": [0, 0], "radius": 50},
              {"kind": "crossing", "near": "[0, 0]", "radius": 50},         # a point passed as a string
              {"kind": "crossing", "near": "0, 0", "radius": "50"},         # string number
              {"kind": "crossing", "near": {"x": 0, "y": 0}, "radius": 50.0}]
    results = [ts.call("list_features", s) for s in shapes]
    assert all(r["ok"] and r["count"] >= 4 for r in results), results
    assert ts.call("check_point", {"x": "-5", "y": "4.2"})["surface"] == "sidewalk"
    assert ts.call("plan_route", {"from": "[20, 4.5]", "to": [20, -4.5]})["crossings"] == ["crossing_1"]


def test_errors_say_what_is_wrong_and_show_an_example():
    ts = make()
    e = ts.call("list_features", {"kind": "crossing", "near": "somewhere"})["error"]
    assert "bad argument" in e and "'near' must be a point" in e and "Example: <tool name=\"list_features\">" in e
    assert "must be one of" in ts.call("list_features", {"kind": "spaceship"})["error"]
    assert "'id' is required" in ts.call("get_feature", {})["error"]
    assert "no feature with id" in ts.call("get_feature", {"id": "zzz"})["error"]
    assert "'type' must be one of" in ts.call("get_scenario_template", {"type": "nope"})["error"]
    assert "'code' is empty" in ts.call("submit_script", {"code": ""})["error"]


def test_system_prompt_carries_a_working_example_per_tool():
    p = system_prompt()
    assert '<tool name="list_features">{"kind": "crossing", "control": "zebra"}</tool>' in p
    assert "{{" not in p
