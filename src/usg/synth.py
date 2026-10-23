"""Synthetic OSM block: lets the whole pipeline (and the tests) run with no network access."""
from __future__ import annotations

from . import geo

LAT0, LON0 = 48.1500, 11.5800


def synthetic_osm() -> str:
    proj = geo.Projection(LAT0, LON0)
    nodes: dict[int, tuple[float, float, dict]] = {}
    ways: list[tuple[int, list[int], dict]] = []
    nid = [1000]
    wid = [5000]
    keyed: dict[tuple[float, float], int] = {}

    def N(x: float, y: float, **tags) -> int:
        k = (round(x, 2), round(y, 2))
        if k in keyed and not tags:
            return keyed[k]
        if k in keyed:
            nodes[keyed[k]][2].update(tags)
            return keyed[k]
        nid[0] += 1
        lat, lon = proj.to_latlon(x, y)
        nodes[nid[0]] = (lat, lon, dict(tags))
        keyed[k] = nid[0]
        return nid[0]

    def W(pts, **tags):
        wid[0] += 1
        ids = [pt if isinstance(pt, int) else N(*pt) for pt in pts]
        ways.append((wid[0], ids, tags))

    # Main Street (E-W): secondary, signalised junction with Oak Avenue at origin, T-junction with Elm Lane
    N(12, 0, highway="crossing", crossing="traffic_signals")
    N(-12, 0, highway="crossing", crossing="traffic_signals")
    N(-70, 0, highway="crossing", crossing="zebra")
    N(0, 12, highway="crossing", crossing="traffic_signals")
    N(0, -12, highway="crossing", crossing="traffic_signals")
    N(8, -8, highway="traffic_signals")
    N(-8, 8, highway="traffic_signals")
    W([(-150, 0), (-100, 0), (-70, 0), (-12, 0), (0, 0), (12, 0), (60, 0), (150, 0)],
      highway="secondary", name="Main Street", lanes="2", maxspeed="50")
    W([(0, -120), (0, -12), (0, 0), (0, 12), (0, 120)], highway="residential", name="Oak Avenue",
      lanes="2", maxspeed="30")
    W([(-100, 0), (-100, 100)], highway="residential", name="Elm Lane", lanes="2", maxspeed="30")

    # street furniture
    N(60, 4.6, highway="bus_stop", name="Park Gate", public_transport="platform", bus="yes")
    N(64, 4.3, amenity="bench")
    N(57, 4.4, amenity="waste_basket")
    N(25, -4.4, amenity="waste_basket")
    N(-30, 4.4, amenity="waste_basket")
    for x in (-130, -110, -45, -25, 25, 45, 100, 130):
        N(x, 4.8, natural="tree")
        N(x, -4.8, natural="tree")
    N(-72, 4.8, highway="street_lamp")

    # buildings: four quadrants, set back from the 5.25 m road+sidewalk edge
    def B(x0, y0, x1, y1, levels=4):
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        W(pts, building="yes", **{"building:levels": str(levels)})

    B(10, 10, 55, 45, 5)
    B(62, 10, 110, 40, 3)
    B(10, -50, 50, -10, 6)
    B(58, -45, 120, -10, 4)
    B(-95, -45, -12, -10, 5)
    B(-140, -45, -105, -12, 3)
    B(-95, 10, -60, 40, 4)
    B(-140, 10, -108, 50, 3)
    B(10, 55, 50, 100, 7)

    # park NW with a footway, a fence and a pond
    W([(-60, 15), (-12, 15), (-12, 70), (-60, 70), (-60, 15)], leisure="park")
    W([(-55, 16), (-30, 40), (-14, 68)], highway="footway", name="Park path")
    W([(-60, 15), (-60, 70)], barrier="fence")
    W([(-40, 55), (-30, 55), (-30, 62), (-40, 62), (-40, 55)], natural="water")
    # a rail line south (non-walkable barrier)
    W([(-150, -90), (150, -90)], railway="rail")

    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="usg-synth">']
    for i, (lat, lon, tags) in nodes.items():
        out.append(f'<node id="{i}" lat="{lat:.7f}" lon="{lon:.7f}">')
        out += [f'<tag k="{k}" v="{v}"/>' for k, v in tags.items()]
        out.append('</node>')
    for i, refs, tags in ways:
        out.append(f'<way id="{i}">')
        out += [f'<nd ref="{r}"/>' for r in refs]
        out += [f'<tag k="{k}" v="{v}"/>' for k, v in tags.items()]
        out.append('</way>')
    out.append('</osm>')
    return "\n".join(out)
