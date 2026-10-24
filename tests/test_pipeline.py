import json
import xml.etree.ElementTree as ET

import pytest

from usg import osm, synth, xodr
from usg.dsl import MapQuery
from usg.mapmodel import MapModel
from usg.sandbox import check_policy, PolicyError, run_script
from usg.scenario_types import ARCHETYPES
from usg.validate import validate


@pytest.fixture(scope="module")
def model():
    return osm.build_map(synth.synthetic_osm())


@pytest.fixture(scope="module")
def map_json(model, tmp_path_factory):
    p = tmp_path_factory.mktemp("map") / "scene_map.json"
    model.save(p)
    return p


# ------------------------------------------------------------------ map
def test_map_structure(model):
    assert len(model.junctions) == 2
    assert {c.control for c in model.crossings} == {"signals", "zebra"}
    assert any(p.ptype == "bus_stop" for p in model.props)
    assert len(model.buildings) >= 8


def test_json_roundtrip(model):
    m2 = MapModel.from_dict(json.loads(json.dumps(model.to_dict())))
    assert len(m2.roads) == len(model.roads)
    assert m2.surface_at((-5, 4.2)) == "sidewalk"
    assert m2.surface_at((0, 0.2)) == "road"


def test_crossing_sides(model):
    q = MapQuery(model)
    a, b = q.crossing_side("crossing_1", "start"), q.crossing_side("crossing_1", "end")
    assert a.y < 0 < b.y                       # road_3 runs +x: right kerb is -y
    assert model.surface_at(a.xy()) == model.surface_at(b.xy()) == "sidewalk"


def test_ped_route_uses_crossing(model):
    r = model.ped_graph.route((20, 4.5), (20, -4.5))
    assert r and r["crossings"] == ["crossing_1"]


def test_xodr_links(model, tmp_path):
    xodr.export_xodr(model, tmp_path / "m.xodr")
    root = ET.parse(tmp_path / "m.xodr").getroot()
    assert len(root.findall("road")) == len(model.roads) + sum(len(j.findall("connection")) for j in root.findall("junction"))


def test_xodr_objects_and_signals_stay_on_their_road(model, tmp_path):
    """esmini warned "s too large, track N only X m long" for a crossing centred in a trimmed stub."""
    xodr.export_xodr(model, tmp_path / "m.xodr")
    for road in ET.parse(tmp_path / "m.xodr").getroot().findall("road"):
        length = float(road.get("length"))
        for e in list(road.iter("object")) + list(road.iter("signal")):
            assert -1e-6 <= float(e.get("s")) <= length + 1e-6, (road.get("id"), e.get("id"))


# ------------------------------------------------------------------ the 7 archetypes
@pytest.mark.parametrize("sid", sorted(ARCHETYPES))
def test_reference_scenarios_pass(sid, map_json):
    res = run_script(ARCHETYPES[sid]["template"], map_json, "synthetic.xodr")
    assert res.ok, res.feedback()
    assert not [i for i in res.issues if i["severity"] == "error"]
    root = ET.fromstring(res.xosc)
    tasks = root.findall(".//VRTask")
    assert tasks
    cats = {t.get("category") for t in tasks}
    expected = {"ptp_env": "ptp_env", "ptp_road": "ptp_road", "cpath": "constrained_path",
                "env_con": "env_constrained", "dyn_nav": "dynamic"}
    if sid in expected:
        assert expected[sid] in cats
    # standard OpenSCENARIO skeleton
    assert root.find("./Storyboard/Init") is not None
    assert root.find(".//UserDefinedAction/CustomCommandAction[@type='VR_TASK']") is not None


def test_dep_comp_ordering(map_json):
    res = run_script(ARCHETYPES["dep_comp"]["template"], map_json)
    ids = [t["id"] for t in res.spec["tasks"]]
    assert [t["depends_on"] for t in res.spec["tasks"]] == [[], [ids[0]], [ids[1]]]
    root = ET.fromstring(res.xosc)
    conds = [c.get("name") for c in root.iter("Condition")]
    assert "T2After1" in conds and "T3After2" in conds


# ------------------------------------------------------------------ validator catches mistakes
BAD_TARGET = '''
from usg.dsl import *
b = MAP.buildings()[0]
scenario = ScenarioBuilder("x", MAP, scenario_type="ptp_env")
scenario.user(MAP.crossing_side("crossing_1", "start"))
scenario.go_to(at(b["center"][0], b["center"][1]), "go", timeout=60)
'''


def test_validator_rejects_target_in_building(map_json):
    res = run_script(BAD_TARGET, map_json)
    assert not res.ok
    assert any(i["code"] == "target_unreachable" for i in res.issues)


TIMEOUT_SHORT = '''
from usg.dsl import *
scenario = ScenarioBuilder("x", MAP, scenario_type="ptp_env")
scenario.user(MAP.sidewalk_at("road_3", "left", 20))
scenario.go_to(MAP.sidewalk_at("road_3", "left", 140), "go far", timeout=10)
'''


def test_validator_timeout_feasibility(map_json):
    res = run_script(TIMEOUT_SHORT, map_json)
    assert any(i["code"] == "timeout_too_short" for i in res.issues)


WRONG_TYPE = '''
from usg.dsl import *
scenario = ScenarioBuilder("x", MAP, scenario_type="dyn_nav")
scenario.user(MAP.crossing_side("crossing_1", "start"))
scenario.cross("crossing_1", "start", "cross", timeout=60)
'''


def test_archetype_requirements_enforced(map_json):
    res = run_script(WRONG_TYPE, map_json)
    assert any(i["code"] == "arch_dyn_nav_mover" for i in res.issues)


# ------------------------------------------------------------------ security
ATTACKS = {
    "import_os": "import os\nscenario = None",
    "from_os": "from os import system\n",
    "dunder": "x = ().__class__.__bases__[0].__subclasses__()\n",
    "open": "open('x.txt','w').write('hi')\n",
    "eval": "eval('1+1')\n",
    "getattr": "getattr(MAP, '_m')\n",
    "private": "m = MAP._m\n",
    "format_escape": "s = '{0.__class__}'.format(MAP)\n",
    "write_xml": "scenario = ScenarioBuilder('x', MAP)\nscenario.write('a.xosc')\n",
    "class": "class A: pass\n",
    "import_sub": "import subprocess\n",
    "dunder_import": "__import__('os')\n",
}


@pytest.mark.parametrize("name", sorted(ATTACKS))
def test_policy_blocks(name):
    with pytest.raises(PolicyError):
        check_policy(ATTACKS[name])


def test_runtime_infinite_loop_times_out(map_json):
    res = run_script("while True:\n    pass\n", map_json, timeout=4)
    assert not res.ok and "timed out" in res.error


def test_runtime_memory_bomb_contained(map_json):
    res = run_script("x = [0] * (10 ** 10)\n", map_json, timeout=15, mem_mb=512)
    assert not res.ok


def test_script_without_scenario(map_json):
    res = run_script("x = 1\n", map_json)
    assert not res.ok and "scenario" in res.error


def test_runtime_error_reports_line(map_json):
    res = run_script("from usg.dsl import *\nx = MAP.crossing_side('nope')\n", map_json)
    assert not res.ok and "line 2" in res.error


def test_cannot_escape_via_dsl_objects(map_json):
    # the string-format trick and attribute walking are the classic escapes; both are blocked statically
    for code in ("x = MAP.overview.__globals__\n", "x = 'a'.format\n"):
        with pytest.raises(PolicyError):
            check_policy(code)


# ------------------------------------------------------------------ regression: narrow one-way street (found on a real Overpass map)
def _variant_map(oneway_lanes: str = "1"):
    """The synthetic city with Elm Lane turned into a 3.25 m one-way single-lane street."""
    import re
    text = synth.synthetic_osm()
    way = re.search(r'(<way id="\d+">(?:(?!</way>).)*?k="name" v="Elm Lane".*?)</way>', text, re.S).group(1)
    new = re.sub(r'<tag k="lanes" v="\d+"/>', f'<tag k="lanes" v="{oneway_lanes}"/><tag k="oneway" v="yes"/>', way)
    return osm.build_map(text.replace(way, new))


def test_single_lane_oneway_lane_centre_is_inside_the_road():
    m = _variant_map()
    from usg.dsl import MapQuery
    q = MapQuery(m)
    elm = next(r for r in m.roads if r.name == "Elm Lane")
    assert elm.oneway and elm.lanes == 1
    pts = q.drive_route(elm.id, 10, 80, "forward")
    assert all(m.surface_at(p.xy()) == "road" for p in pts), [(p.xy(), m.surface_at(p.xy())) for p in pts]
    # the lane centre of a one-lane road is its centre-line
    assert max(abs(geo_t) for geo_t in (m.nearest_road(p.xy())[3] for p in pts)) < 0.05


def test_validator_tolerates_edge_rounding_but_not_the_sidewalk():
    from usg.validate import _on_road, _road_hint
    m = osm.build_map(synth.synthetic_osm())
    edge = (20.0, -3.3)          # 5 cm outside a 6.5 m road's edge: rounding noise
    assert _on_road(m, edge) and not _on_road(m, (20.0, -4.6))           # 4.6 is mid-sidewalk
    assert "Main Street" in _road_hint(m, (20.0, -4.6)) and "m wide" in _road_hint(m, (20.0, -4.6))


OFF_ROAD_CAR = '''
from usg.dsl import *
scenario = ScenarioBuilder("x", MAP, scenario_type="dyn_nav")
scenario.user(MAP.crossing_side("crossing_3", "start"))
t = scenario.cross("crossing_3", "start", "cross", avoid=["Car1"], timeout=60)
scenario.vehicle("Car1", at(-80, -4.6), [at(-60, -4.6)], speed=8)
'''


def test_off_road_vehicle_error_says_how_to_fix_it(map_json):
    res = run_script(OFF_ROAD_CAR, map_json)
    msg = " ".join(i["message"] for i in res.issues if i["code"] == "vehicle_off_road")
    assert "nearest road" in msg and "MAP.drive_route" in msg


def test_all_reference_scripts_survive_a_narrow_oneway_street(tmp_path):
    """Templates must adapt to maps other than the synthetic one."""
    from usg.sandbox import execute_script
    m = MapModel.from_dict(json.loads(json.dumps(_variant_map().to_dict())))
    for sid, a in ARCHETYPES.items():
        res = execute_script(a["template"], m, "map.xodr")
        assert res["ok"], (sid, res.get("error") or res["issues"])


# ------------------------------------------------------------------ the constraint axes
from usg.scenario_types import AXES, AXIS_DEFAULTS, axes_label, axes_of


def test_every_archetype_is_a_named_point_on_the_axes():
    for sid, a in ARCHETYPES.items():
        assert set(a["axes"]) == set(AXES)
        assert all(v in AXES[k] for k, v in a["axes"].items())
    # ptp_env is the base task (all defaults); every other archetype moves exactly one axis; no two share a point
    moved = {sid: {k for k, v in a["axes"].items() if v != AXIS_DEFAULTS[k]} for sid, a in ARCHETYPES.items()}
    assert moved["ptp_env"] == set()
    assert all(len(m) == 1 for sid, m in moved.items() if sid != "ptp_env")
    assert len({tuple(sorted(a["axes"].items())) for a in ARCHETYPES.values()}) == len(ARCHETYPES)


@pytest.mark.parametrize("sid", sorted(ARCHETYPES))
def test_axes_inferred_from_the_reference_scenarios_cover_the_archetype(sid, map_json, model):
    res = run_script(ARCHETYPES[sid]["template"], map_json, "synthetic.xodr")
    assert res.ok, res.feedback()
    inferred = axes_of(res.spec, model)
    for axis, value in ARCHETYPES[sid]["axes"].items():
        if value != AXIS_DEFAULTS[axis]:
            assert inferred[axis] == value, (sid, axis, inferred)    # the archetype's own constraint is really present


def test_axes_label_lists_only_non_default_axes():
    assert axes_label(dict(AXIS_DEFAULTS)) == "base task (reach a target)"
    assert axes_label({**AXIS_DEFAULTS, "surface": "road", "dynamic": "movers"}) == "surface=road, dynamic=movers"
