"""Completeness of the 30 m map window: every map element in the window is in the text or in the removal log."""
from pathlib import Path

import pytest

from usg import geo
from usg.training import sampler, window as W

MAP = Path(__file__).resolve().parents[1] / "eval" / "maps" / "paris_center.osm"


@pytest.fixture(scope="module")
def model():
    return sampler.load_tool_server(MAP).model


def test_every_element_is_listed_or_logged(model):
    windows = W.select(model, 60, seed=1)
    assert {k for k, _ in windows} == set(W.KIND_QUOTA)
    for _, c in windows:
        win = W.build(model, c)
        known = {s for v in win["ids"].values() for s in v.split("+")} | {r["id"] for r in win["removed"]}
        loc = lambda p: (p[0] - c[0], p[1] - c[1])
        for items in (model.roads, model.paths, model.barriers):
            for o in items:
                if W.clip_line([loc(p) for p in o.pts]):
                    assert o.id in known, o.id
        for items in (model.props, model.signals, model.junctions, model.crossings):
            for o in items:
                if W.inside(loc(o.pos), 0):
                    assert o.id in known, o.id
        for items in (model.buildings, model.areas):
            for o in items:
                clipped = W.clip_poly([loc(p) for p in o.pts])
                if len(clipped) >= 3 and abs(geo.polygon_area(clipped)) >= 2 * W.MIN_AREA:
                    assert o.id in known, o.id
        text = W.to_text(win)
        for local in win["ids"]:
            assert local in text, local


def test_assumed_sidewalks_stay_off_other_roads(model):
    for _, c in W.select(model, 60, seed=3):
        e = W.build(model, c)["elements"]
        for w in e["sidewalks"]:
            if w["source"] != "assumed":
                continue
            for r in e["roads"]:
                if r["id"] != w["road"]:
                    mid = geo.point_at(w["line"], geo.polyline_length(w["line"]) / 2)[0]
                    assert geo.dist_to_polyline(r["line"], mid) > r["width"] / 2, (w["id"], r["id"])


def test_building_passage_is_open():
    from usg.mapmodel import Building, MapModel, Path as P
    from usg import geo as G
    m = MapModel(G.Projection(0.0, 0.0))
    m.buildings.append(Building(id="building_1", pts=[(0, 0), (10, 0), (10, 10), (0, 10)], height=9))
    m.paths.append(P(id="path_1", pts=[(-2, 5), (12, 5)], width=2, ptype="footway", passage=True))
    m.reindex()
    assert m.surface_at((5, 5)) == "path" and m.surface_at((5, 8)) == "building"


def test_text_is_deterministic_and_coordinates_stay_inside(model):
    _, c = W.select(model, 5, seed=2)[0]
    win = W.build(model, c)
    assert W.to_text(win) == W.to_text(W.build(model, c))
    e = win["elements"]
    for key in ("roads", "paths", "crossings", "barriers"):
        for x in e[key]:
            assert all(W.inside(p, 0.01) for p in x["line"]), x["id"]
