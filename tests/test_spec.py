"""The L2 specification language: structure/expansion, XML round trip, quantitative monitor, explicit spec tasks."""
import xml.etree.ElementTree as ET

import pytest

from usg import osm, synth
from usg.dsl import MapQuery, ScenarioBuilder, at
from usg.sandbox import execute_script
from usg.spec import SpecError, atoms_in, describe, from_xml, prepare, to_xml
from usg.spec import formula as F
from usg.spec.monitor import Monitor, Sample, goal_status


# ------------------------------------------------------------------ helpers
def S(x=0.0, y=0.0, gaze=0.0, speed=1.3, surface="sidewalk", ents=None, signals=None, events=()):
    return Sample(x, y, gaze, speed, surface, ents or {}, signals or {}, frozenset(events))


def walk(xs, **kw):
    return [S(x=x, **kw) for x in xs]


DISC = {"kind": "disc", "x": 10.0, "y": 0.0, "r": 1.0}
IN = {"op": "in_zone", "zone": DISC}


# ------------------------------------------------------------------ structure, errors, expansion
def test_library_definitions_expand_to_core_operators():
    core = prepare({"op": "call", "name": "reach", "args": {"zone": DISC}})
    assert core["op"] == "eventually" and core["arg"]["op"] == "in_zone" and core["end"] is None
    assert not [n for n in F.walk(core) if n["op"] in ("call", "then")]


def test_then_is_nested_eventually():
    core = prepare({"op": "then", "args": [IN, {"op": "in_zone", "zone": {**DISC, "x": 20.0}}]})
    assert core["op"] == "eventually" and core["arg"]["op"] == "and" and core["arg"]["args"][1]["op"] == "eventually"


@pytest.mark.parametrize("bad, fragment", [
    ({"op": "fly"}, "unknown op 'fly'"),
    ({"op": "in_zone"}, "needs 'zone'"),
    ({"op": "in_zone", "zone": {"kind": "disc", "x": 1}}, "needs the field"),
    ({"op": "look_at", "angle": 30}, "exactly one of"),
    ({"op": "look_at", "entity": "A", "angle": 300}, "(0,180]"),
    ({"op": "dist_ge", "entity": "A", "d": -1}, ">= 0"),
    ({"op": "always", "arg": IN, "start": 5, "end": 2}, "end"),
    ({"op": "and", "args": []}, ">= 1"),
    ({"op": "on_surface", "surface": "lava"}, "one of"),
    ({"op": "signal_is", "signal": "s", "state": "blue"}, "green"),
    ({"op": "event", "name": "e", "oops": 1}, "does not take"),
    ("reach", "object"),
])
def test_bad_formulas_get_actionable_errors(bad, fragment):
    with pytest.raises(SpecError) as e:
        prepare(bad)
    assert fragment in str(e.value)


def test_errors_name_the_json_path():
    with pytest.raises(SpecError) as e:
        prepare({"op": "and", "args": [IN, {"op": "dist_le", "entity": "A", "d": "far"}]}, path="tasks[0].goal")
    assert "tasks[0].goal.args[1].d" in str(e.value)


def test_unknown_missing_and_extra_call_arguments():
    for call, frag in [({"op": "call", "name": "nope", "args": {}}, "unknown definition"),
                       ({"op": "call", "name": "reach", "args": {}}, "missing"),
                       ({"op": "call", "name": "reach", "args": {"zone": DISC, "x": 1}}, "unexpected")]:
        with pytest.raises(SpecError) as e:
            prepare(call)
        assert frag in str(e.value)


def test_wrong_argument_value_is_caught_after_substitution():
    with pytest.raises(SpecError):
        prepare({"op": "call", "name": "keep_clear", "args": {"entity": "Car1", "d": "close", "seconds": 5}})


def test_user_definitions_compose_and_recursion_is_rejected():
    defs = {"safe_cross": {"params": ["z", "sig"], "body": {"op": "and", "args": [
        {"op": "call", "name": "reach", "args": {"zone": F.P("z")}},
        {"op": "call", "name": "obey_signal", "args": {"zone": F.P("z"), "signal": F.P("sig")}}]}}}
    F.check_defs(defs)
    core = prepare({"op": "call", "name": "safe_cross", "args": {"z": DISC, "sig": "s1"}}, defs)
    assert {"s1"} == F.signals_in(core)
    loop = {"a": {"params": [], "body": {"op": "call", "name": "b", "args": {}}},
            "b": {"params": [], "body": {"op": "call", "name": "a", "args": {}}}}
    F.check_defs(loop)
    with pytest.raises(SpecError) as e:
        prepare({"op": "call", "name": "a", "args": {}}, loop)
    assert "calls itself" in str(e.value)


def test_definition_names_cannot_shadow_the_library():
    with pytest.raises(SpecError):
        F.check_defs({"reach": {"params": [], "body": {"op": "true"}}})


def test_size_limit():
    big = {"op": "and", "args": [{"op": "true"}] * (F.MAX_NODES + 5)}
    with pytest.raises(SpecError) as e:
        prepare(big)
    assert "nodes" in str(e.value)


# ------------------------------------------------------------------ XML and JSON
def test_xml_roundtrip_every_operator():
    f = prepare({"op": "and", "args": [
        {"op": "call", "name": "wait_for_green", "args": {"zone": DISC, "signal": "s"}},
        {"op": "call", "name": "look_point", "args": {"point": [1.5, 2.5], "angle": 40, "seconds": 8}},
        {"op": "call", "name": "stay_near_path", "args": {"path": [[0, 0], [5, 5]], "tol": 2}},
        {"op": "call", "name": "pace", "args": {"vmin": 0.5, "vmax": 2, "seconds": 4}},
        {"op": "call", "name": "obey_signal", "args": {"zone": {"kind": "rect", "cx": 1, "cy": 2, "h": 0.5, "hl": 3, "hw": 2}, "signal": "s"}},
        {"op": "call", "name": "no_event", "args": {"name": "honk"}},
        {"op": "call", "name": "keep_clear", "args": {"entity": "Car1", "d": 2, "seconds": 3}},
        {"op": "call", "name": "reach", "args": {"zone": {"kind": "entity", "name": "Walker1", "r": 2}}}]})
    back = from_xml(ET.fromstring(ET.tostring(to_xml(f), encoding="unicode")))
    assert back == f


def test_describe_is_readable():
    s = describe(prepare({"op": "call", "name": "collision_free", "args": {"entity": "Car1", "r": 0.3}}))
    assert "Car1" in s and "always" in s


def test_json_schema_lists_all_ops():
    assert set(F.OPS) <= set(F.json_schema()["$defs"]["formula"]["properties"]["op"]["enum"])


# ------------------------------------------------------------------ monitor semantics
def test_reach_is_decided_as_soon_as_the_user_arrives():
    f = prepare({"op": "call", "name": "reach", "args": {"zone": DISC}})
    far = walk([0, 2, 4])
    assert goal_status(f, [], far)["status"] == "running"
    near = walk([0, 5, 9.5])
    r = goal_status(f, [], near)
    assert r["status"] == "success" and r["goal"][0] == pytest.approx(0.5)      # margin = r - distance


def test_always_is_violated_for_good_and_satisfied_only_when_the_window_closes():
    f = prepare({"op": "call", "name": "hold", "args": {"zone": DISC, "seconds": 0.5}})
    inside = [S(x=10.0) for _ in range(4)]
    assert goal_status(f, [], inside)["status"] == "running"                     # window [0, 0.5] needs 6 samples
    inside = [S(x=10.0) for _ in range(6)]
    assert goal_status(f, [], inside)["status"] == "success"
    left = [S(x=10.0), S(x=10.0), S(x=15.0)]
    assert goal_status(f, [], left)["status"] == "failed"


def test_interval_semantics_prefix_bounds():
    f = prepare({"op": "eventually", "arg": IN, "start": 0, "end": 0.3})
    m = Monitor(walk([0, 1]), complete=False)
    lo, hi = m.rho(f, 0)
    assert lo < 0 <= hi                                                          # undecided: the window is still open
    lo, hi = Monitor(walk([0, 1, 2, 3, 4]), complete=False).rho(f, 0)
    assert hi < 0                                                                # window closed without the zone


def test_complete_trace_gives_exact_robustness():
    f = prepare({"op": "call", "name": "reach", "args": {"zone": DISC}})
    lo, hi = Monitor(walk([0, 4, 8, 12]), complete=True).rho(f, 0)
    assert lo == hi == pytest.approx(-1.0)                                       # closest approach 2 m from the centre, radius 1 m


def test_collision_free_margin_is_distance_minus_radius():
    ent = {"Car1": (5.0, 0.0, 0.0, 4.0, 2.0)}
    f = prepare({"op": "call", "name": "collision_free", "args": {"entity": "Car1", "r": 0.3}})
    tr = [S(x=0.0, ents=ent), S(x=2.0, ents=ent)]                                # the car's body spans x in [3,7]; closest the user gets: 1.0 m
    lo, hi = Monitor(tr, complete=True).rho(f, 0)
    assert lo == pytest.approx(1.0 - 0.3)
    bad = [S(x=0.0, ents=ent), S(x=3.5, ents=ent)]
    assert goal_status({"op": "true"}, [f], bad)["status"] == "failed"


def test_until_wait_for_green():
    f = prepare({"op": "call", "name": "wait_for_green", "args": {"zone": DISC, "signal": "s"}})
    red = {"s": "red"}
    green = {"s": "green"}
    tr = [S(x=10.0, signals=red), S(x=10.0, signals=red), S(x=10.0, signals=green)]
    assert goal_status(f, [], tr)["status"] == "success"
    left_early = [S(x=10.0, signals=red), S(x=14.0, signals=red)]
    assert goal_status(f, [], left_early)["status"] in ("failed", "running")
    assert goal_status(f, [], left_early + [S(x=14.0, signals=red)] * 3)["status"] == "failed"


def test_signal_violation_only_when_entering_on_red():
    rect = {"kind": "rect", "cx": 0, "cy": 0, "h": 0, "hl": 2, "hw": 2}
    f = prepare({"op": "call", "name": "obey_signal", "args": {"zone": rect, "signal": "s"}})
    enter_red = [S(x=-5, signals={"s": "red"}), S(x=0, signals={"s": "red"})]
    assert Monitor(enter_red, complete=True).rho(f, 0)[0] < 0
    enter_green_then_red = [S(x=-5, signals={"s": "green"}), S(x=0, signals={"s": "green"}), S(x=0, signals={"s": "red"})]
    assert Monitor(enter_green_then_red, complete=True).rho(f, 0)[0] > 0         # the light changing while crossing is fine


def test_stay_on_tolerates_one_second_off_surface():
    f = prepare({"op": "call", "name": "stay_on", "args": {"surface": "pedestrian_infra"}})
    ok = [S(surface="sidewalk")] * 3 + [S(surface="road")] * 5 + [S(surface="sidewalk")] * 20
    assert Monitor(ok, complete=True).rho(f, 0)[0] > 0
    bad = [S(surface="sidewalk")] * 3 + [S(surface="road")] * 20
    assert Monitor(bad, complete=True).rho(f, 0)[0] < 0


def test_look_at_margin_is_angle_minus_error():
    f = prepare({"op": "call", "name": "look_point", "args": {"point": [10, 0], "angle": 30, "seconds": 1}})
    straight = [S(gaze=0.0)] * 4
    assert Monitor(straight, complete=True).rho(f, 0)[0] == pytest.approx(30.0)
    away = [S(gaze=3.14159)] * 4
    assert Monitor(away, complete=True).rho(f, 0)[0] < 0


def test_pace_band():
    f = prepare({"op": "call", "name": "pace", "args": {"vmin": 0.5, "vmax": 2.0, "seconds": 0.3}})
    assert Monitor([S(speed=1.0)] * 6, complete=True).rho(f, 0)[0] == pytest.approx(0.5)
    assert Monitor([S(speed=3.0)] * 6, complete=True).rho(f, 0)[0] < 0


def test_not_swaps_bounds():
    f = {"op": "not", "arg": prepare({"op": "call", "name": "reach", "args": {"zone": DISC}})}
    lo, hi = Monitor(walk([0, 1]), complete=False).rho(f, 0)
    assert lo == -F.BIG and hi < F.BIG


# ------------------------------------------------------------------ explicit spec tasks, end to end
@pytest.fixture(scope="module")
def model():
    return osm.build_map(synth.synthetic_osm())


def _scenario(model, spec_doc, level=2, cycle=True):
    q = MapQuery(model)
    cr = q.crossings(control="signals")[0]
    sc = ScenarioBuilder("spec_test", q, scenario_type="ptp_env")
    sc.user(q.crossing_side(cr["id"], "start", 6.0))
    if cycle:
        sc.signal_cycle(cr["id"], green=12, red=14, initial="red")
    sc.apply_spec(spec_doc, level)
    return sc, cr


def _sig(cr):
    return cr["signal_id"] or f"{cr['id']}_ped"


def _doc(cr):
    return {"tasks": [{
        "name": "cross_safely", "instruction": "Wait for green, look at the light, then cross.",
        "goal": {"op": "then", "args": [
            {"op": "call", "name": "wait_for_green", "args": {"zone": {"kind": "crossing_side", "id": cr["id"], "side": "start", "r": 2.5}, "signal": _sig(cr)}},
            {"op": "call", "name": "reach", "args": {"zone": {"kind": "crossing_side", "id": cr["id"], "side": "end", "r": 2.0}}}]},
        "safety": [{"op": "call", "name": "obey_signal", "args": {"zone": {"kind": "crossing", "id": cr["id"]}, "signal": _sig(cr)}}],
        "timeout": {"initial": 70, "baseline": 110}}]}


def test_spec_task_builds_valid_openscenario_with_formulas(model):
    q = MapQuery(model)
    cr = q.crossings(control="signals")[0]
    sc, _ = _scenario(model, _doc(cr))
    xml = sc.to_xml_string()
    root = ET.fromstring(xml)
    sp = root.find(".//VRTask/Spec")
    assert sp is not None and sp.get("origin") == "spec"
    goal = from_xml(sp.find("Goal/F"))
    assert goal["op"] == "eventually" and F.signals_in(goal) == {_sig(cr)}
    assert len(sp.findall("Safety/F")) == 1
    assert root.find(".//UserDefinedAction/CustomCommandAction[@type='VR_TASK']") is not None


def test_helper_made_tasks_ship_formulas_too(model):
    q = MapQuery(model)
    cr = q.crossings(control="signals")[0]
    sc = ScenarioBuilder("legacy", q, scenario_type="ptp_env")
    sc.user(q.crossing_side(cr["id"], "start", 4.0))
    sc.signal_cycle(cr["id"], green=12, red=14)
    sc.cross(cr["id"], "start", "Cross", timeout=60)
    root = ET.fromstring(sc.to_xml_string())
    sp = root.find(".//VRTask/Spec")
    assert sp.get("origin") == "helper"
    assert F.signals_in(from_xml(sp.find("Safety/F"))) == {_sig(cr)}


def test_nominal_walker_waits_for_green_and_satisfies_the_spec(model):
    from usg.spec import oracle
    q = MapQuery(model)
    cr = q.crossings(control="signals")[0]
    sc, _ = _scenario(model, _doc(cr))
    spec = sc.to_spec()
    mg = oracle.margins(spec, model)[1]
    assert mg["ok"], mg
    assert mg["duration"] >= 12                                                   # it waited for the red phase to end


def test_level_one_forbids_own_definitions(model):
    q = MapQuery(model)
    doc = {"defs": {"mine": {"params": [], "body": {"op": "true"}}}, "tasks": [{"name": "t", "instruction": "x", "goal": {"op": "call", "name": "mine", "args": {}}}]}
    sc = ScenarioBuilder("l1", q, scenario_type="ptp_env")
    with pytest.raises(SpecError) as e:
        sc.apply_spec(doc, level=1)
    assert "not allowed" in str(e.value)


def test_spec_task_with_unknown_entity_is_rejected_by_the_validator(model):
    q = MapQuery(model)
    cr = q.crossings(control="signals")[0]
    doc = _doc(cr)
    doc["tasks"][0]["safety"].append({"op": "call", "name": "collision_free", "args": {"entity": "Ghost", "r": 0.3}})
    script = f'''
cr = MAP.crossings(control="signals")[0]
scenario = ScenarioBuilder("t", MAP, scenario_type="ptp_env")
scenario.user(MAP.crossing_side(cr["id"], "start", 6.0))
scenario.signal_cycle(cr["id"], green=12, red=14)
scenario.apply_spec({doc!r}, 2)
'''
    import tempfile, pathlib
    from usg.mapmodel import MapModel
    p = pathlib.Path(tempfile.mkdtemp()) / "m.json"
    model.save(p)
    res = execute_script(script, MapModel.load(p))
    assert not res["ok"] and "spec_unknown_entity" in {i["code"] for i in res["issues"]}


def test_look_task_without_any_zone_is_valid(model):
    q = MapQuery(model)
    cr = q.crossings(control="signals")[0]
    sc = ScenarioBuilder("look_only", q, scenario_type="ptp_env")
    sc.user(q.crossing_side(cr["id"], "start", 4.0))
    sc.vehicle("Car1", q.drive_route(q.crossings()[0]["road"], 0, 40)[0], q.drive_route(q.crossings()[0]["road"], 0, 40)[1:], speed=6)
    sc.apply_spec({"tasks": [{"name": "check_traffic", "instruction": "Look at the approaching car.", "timeout": {"initial": 20, "baseline": 30},
                              "goal": {"op": "call", "name": "look", "args": {"entity": "Car1", "angle": 40, "seconds": 15}}}]})
    from usg.validate import validate
    issues = validate(sc.to_spec(), model)
    assert not [i for i in issues if i.severity == "error" and i.code in ("task_no_target",)]


# ------------------------------------------------------------------ the two-stage agent (specification first, world second)
import json

from usg.agent.loop import parse_tool_call, run_agent
from usg.spec.document import check_document, document_from_spec
from usg.tools import ToolServer, system_prompt, tool_specs


class _Scripted:
    context_tokens = 16000

    def __init__(self, replies):
        self.replies, self.i, self.seen = replies, 0, []

    def chat(self, messages, max_tokens=1800, on_token=None):
        self.seen.append([dict(m) for m in messages])
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        return r


def _tool(name, args):
    return f'<tool name="{name}">{json.dumps(args)}</tool>'


WORLD = '''from usg.dsl import *
cr = MAP.crossings(control="signals")[0]
scenario = ScenarioBuilder("two_stage", MAP, scenario_type="custom", description="wait and cross")
scenario.user(MAP.crossing_side(cr["id"], "start", 6.0))
scenario.signal_cycle(cr["id"], green=12, red=14, initial="red")
handles = scenario.apply_spec(SPEC)
'''


@pytest.fixture()
def tools2():
    t = ToolServer(level=2)
    t.load_osm(synth.synthetic_osm())
    return t


def test_prompt_and_tools_depend_on_the_level():
    assert "submit_spec" not in [t["name"] for t in tool_specs(0)]
    assert {"submit_spec", "list_atoms"} <= {t["name"] for t in tool_specs(1)}
    assert "own definitions" in system_prompt(2) and "own definitions are not available" in system_prompt(1)
    assert "go_to(" in system_prompt(0) and "apply_spec" in system_prompt(2)


def test_parse_submit_spec_and_bare_json_block():
    c = parse_tool_call('<tool name="submit_spec">```json\n{"tasks": [{"name": "a", "goal": {"op": "true"}}]}\n```</tool>')
    assert c.name == "submit_spec" and c.args["tasks"][0]["name"] == "a"
    c = parse_tool_call('Here it is:\n```json\n{"tasks": [{"name": "a", "instruction": "x", "goal": {"op": "true"}}]}\n```')
    assert c.name == "submit_spec"


def test_script_is_refused_before_a_specification_exists(tools2):
    r = tools2.call("submit_script", {"code": WORLD})
    assert r["ok"] and not r["accepted"] and "submit_spec" in r["feedback"]


def test_spec_errors_are_actionable_and_do_not_store(tools2):
    r = tools2.call("submit_spec", {"tasks": [{"name": "t", "instruction": "x", "goal": {"op": "call", "name": "reach", "args": {}}}]})
    assert r["ok"] and not r["accepted"] and "missing" in r["feedback"] and tools2.spec is None


def test_full_two_stage_run_produces_a_scenario_with_formulas(tools2):
    q = tools2.q
    cr = q.crossings(control="signals")[0]
    sig = cr["signal_id"] or f"{cr['id']}_ped"
    spec = _doc_for(cr, sig)
    llm = _Scripted([_tool("submit_spec", spec), f'<tool name="submit_script">\n```python\n{WORLD}\n```\n</tool>', "Done."])
    events = list(run_agent(llm, tools2, "wait for green then cross", max_steps=8))
    assert events[-1]["kind"] == "done", events[-3:]
    res = tools2.result
    assert res["level"] == 2 and res["spec_doc"]["tasks"][0]["name"] == "wait_then_cross"
    assert "Reference SPECIFICATION" in llm.seen[0][1]["content"]
    root = ET.fromstring(res["xosc"])
    assert root.find(".//VRTask/Spec").get("origin") == "spec"


def _doc_for(cr, sig):
    return {"tasks": [{"name": "wait_then_cross", "instruction": "Wait for green, then cross.",
                       "goal": {"op": "then", "args": [
                           {"op": "call", "name": "wait_for_green", "args": {"zone": {"kind": "crossing_side", "id": cr["id"], "side": "start", "r": 3}, "signal": sig}},
                           {"op": "call", "name": "cross", "args": {"far_zone": {"kind": "crossing_side", "id": cr["id"], "side": "end", "r": 2}}}]},
                       "safety": [{"op": "call", "name": "obey_signal", "args": {"zone": {"kind": "crossing", "id": cr["id"]}, "signal": sig}}],
                       "timeout": {"initial": 70, "baseline": 110}}]}


def test_script_that_ignores_the_specification_is_rejected(tools2):
    cr = tools2.q.crossings(control="signals")[0]
    sig = cr["signal_id"] or f"{cr['id']}_ped"
    assert tools2.call("submit_spec", _doc_for(cr, sig))["accepted"]
    ignoring = WORLD.replace("handles = scenario.apply_spec(SPEC)", 'scenario.go_to(MAP.crossing_side(cr["id"], "end"), "Cross", timeout=60)')
    r = tools2.call("submit_script", {"code": ignoring})
    assert not r["accepted"] and "spec_not_applied" in r["feedback"]


def test_level_one_rejects_own_definitions(tools2):
    tools2.level = 1
    r = tools2.call("submit_spec", {"defs": {"mine": {"params": [], "body": {"op": "true"}}},
                                    "tasks": [{"name": "t", "instruction": "x", "goal": {"op": "call", "name": "mine", "args": {}}}]})
    assert not r["accepted"] and "not allowed" in r["feedback"]


def test_the_reference_documents_of_all_seven_types_apply_cleanly(tools2):
    from usg.sandbox import run_script
    for sid, a in ARCHETYPES_FOR_TEST.items():
        res = run_script(a["template"], tools2.map_path, "map.xodr")
        assert res.ok, (sid, res.feedback())
        doc = document_from_spec(res.spec)
        chk = check_document(doc, tools2.q, 1)
        assert chk["ok"], (sid, chk["errors"])


from usg.scenario_types import ARCHETYPES as ARCHETYPES_FOR_TEST  # noqa: E402


def test_participant_is_placed_automatically_when_the_script_omits_the_user(model):
    q = MapQuery(model)
    cr = q.crossings(control="signals")[0]
    sc = ScenarioBuilder("auto_user", q, scenario_type="custom")
    sc.signal_cycle(cr["id"], green=12, red=14, initial="red")
    sc.apply_spec(_doc(cr))
    spec = sc.to_spec()
    user = next(e for e in spec["entities"] if e["role"] == "user")
    assert model.surface_at((user["start"]["x"], user["start"]["y"])) in ("sidewalk", "path", "ground")
    goal = spec["tasks"][0]["goal"]
    z = F.zones_in(goal)[0]
    d = ((user["start"]["x"] - z["x"]) ** 2 + (user["start"]["y"] - z["y"]) ** 2) ** 0.5
    assert 5 <= d <= 40
    from usg.validate import validate
    assert not [i for i in validate(spec, model) if i.severity == "error"]


# ------------------------------------------------------------------ vision: an annotated map image for the model
def test_map_image_is_a_png_with_labels(model):
    from usg.render import map_image_png
    png = map_image_png(model)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 10_000


def test_vision_attaches_the_image_to_the_first_message_only(tools2):
    tools2.vision = True
    llm = _Scripted(["Nothing to do."] * 6)
    list(run_agent(llm, tools2, "walk to the bus stop", max_steps=2))
    first_user = llm.seen[0][1]["content"]
    assert isinstance(first_user, list) and first_user[1]["type"] == "image_url"
    assert first_user[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "top-down view" in first_user[0]["text"]
    assert all(isinstance(m["content"], str) for m in llm.seen[-1][2:])          # later messages stay plain text


def test_without_vision_the_first_message_is_plain_text(tools2):
    llm = _Scripted(["Nothing to do."] * 6)
    list(run_agent(llm, tools2, "walk to the bus stop", max_steps=1))
    assert isinstance(llm.seen[0][1]["content"], str)


def test_local_model_finds_its_vision_projector(tmp_path):
    from usg.localllm import LocalModel
    d = tmp_path / "pub" / "Model-GGUF"
    d.mkdir(parents=True)
    (d / "Model-Q4.gguf").write_bytes(b"x")
    m = LocalModel("pub/Model-GGUF/Model-Q4.gguf", d / "Model-Q4.gguf", 1)
    assert m.mmproj is None
    (d / "mmproj-Model-BF16.gguf").write_bytes(b"x")
    assert m.mmproj is not None and m.mmproj.name.startswith("mmproj")


def test_compaction_handles_multimodal_messages():
    from usg.agent.loop import compact
    from usg.llm import with_image
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": with_image("hello", b"\x89PNG" + b"0" * 100)}] + \
           [{"role": "assistant" if i % 2 else "user", "content": "Tool result " + "x" * 3000} for i in range(10)]
    out = compact(msgs, 2000)
    assert isinstance(out[1]["content"], list) and len(out) == len(msgs)
