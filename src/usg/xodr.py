"""MapModel -> OpenDRIVE 1.6, from the very same metric data the renderer uses.

Roads are exported *trimmed* at junctions (matching ``Road.trim_*``); inside junctions
we emit connecting roads. Coordinates are the shared local ENU frame, so a
``WorldPosition`` in the scenario, a vertex in the 3D scene and an ``s,t`` on the
XODR road all refer to the same physical point.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from . import geo
from .mapmodel import MapModel, Road


def _f(v: float) -> str:
    return f"{v:.6f}"


def _lane_counts(r: Road) -> tuple[int, int, float]:
    """(left_driving, right_driving, lane_width)."""
    if r.oneway:
        n = max(1, r.lanes)
        return 0, n, r.width / n
    per = max(1, r.lanes // 2)
    return per, per, r.width / (2 * per)


def _add_geometry(plan: ET.Element, pts: list[geo.Pt]) -> float:
    s = 0.0
    for a, b in zip(pts[:-1], pts[1:]):
        length = geo.dist(a, b)
        if length < 1e-6:
            continue
        g = ET.SubElement(plan, "geometry", s=_f(s), x=_f(a[0]), y=_f(a[1]),
                          hdg=_f(geo.heading(a, b)), length=_f(length))
        ET.SubElement(g, "line")
        s += length
    return s


def _lane(parent: ET.Element, lid: int, ltype: str, width: float, mark: bool = False) -> None:
    ln = ET.SubElement(parent, "lane", id=str(lid), type=ltype, level="false")
    ET.SubElement(ln, "width", sOffset="0", a=_f(width), b="0", c="0", d="0")
    if mark and ltype == "driving":
        ET.SubElement(ln, "roadMark", sOffset="0", type="solid", weight="standard", color="white", width="0.12")


def export_xodr(m: MapModel, path: str | Path, rule: str = "RHT") -> dict:
    """Write the XODR and return an id map {map_road_id: xodr_road_id}."""
    root = ET.Element("OpenDRIVE")
    x0, y0, x1, y1 = m.bounds
    hdr = ET.SubElement(root, "header", revMajor="1", revMinor="6", name="usg", version="1.0", date="",
                        north=_f(y1), south=_f(y0), east=_f(x1), west=_f(x0), vendor="usg")
    geo_ref = ET.SubElement(hdr, "geoReference")
    geo_ref.text = (f"+proj=tmerc +lat_0={m.proj.lat0:.9f} +lon_0={m.proj.lon0:.9f} "
                    f"+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs")

    byid = {r.id: i + 1 for i, r in enumerate(m.roads)}
    node_roads: dict[str, list[tuple[Road, bool]]] = {}
    for r in m.roads:
        node_roads.setdefault(r.start_node, []).append((r, True))
        node_roads.setdefault(r.end_node, []).append((r, False))
    jx_of_node: dict[str, str] = {}
    jn_ids: dict[str, int] = {}
    for k, j in enumerate(m.junctions, 1):
        jn_ids[j.id] = k
        for rid in j.roads:
            r = m.road(rid)
            node = r.start_node if geo.dist(r.pts[0], j.pos) < geo.dist(r.pts[-1], j.pos) else r.end_node
            jx_of_node[node] = j.id

    trimmed: dict[str, list[geo.Pt]] = {}
    for r in m.roads:
        trimmed[r.id] = geo.sub_polyline(r.pts, r.trim_start, r.length - r.trim_end)

    for r in m.roads:
        rid = byid[r.id]
        pts = trimmed[r.id]
        road = ET.SubElement(root, "road", name=r.name or r.id, length="0", id=str(rid), junction="-1", rule=rule)
        link = ET.SubElement(road, "link")
        for node, is_start in ((r.start_node, True), (r.end_node, False)):
            tag = "predecessor" if is_start else "successor"
            if node in jx_of_node:
                ET.SubElement(link, tag, elementType="junction", elementId=str(jn_ids[jx_of_node[node]]))
            else:
                others = [(o, s) for o, s in node_roads.get(node, []) if o.id != r.id]
                if len(others) == 1:
                    o, o_start = others[0]
                    ET.SubElement(link, tag, elementType="road", elementId=str(byid[o.id]),
                                  contactPoint="start" if o_start else "end")
        t = ET.SubElement(road, "type", s="0", type="town")
        ET.SubElement(t, "speed", max=_f(r.speed), unit="m/s")
        plan = ET.SubElement(road, "planView")
        road.set("length", _f(_add_geometry(plan, pts)))
        ET.SubElement(ET.SubElement(road, "elevationProfile"), "elevation", s="0", a="0", b="0", c="0", d="0")
        lanes = ET.SubElement(road, "lanes")
        sec = ET.SubElement(lanes, "laneSection", s="0", singleSide="false")
        nl, nr, lw = _lane_counts(r)
        if nl or r.sidewalk_left > 0:
            left = ET.SubElement(sec, "left")
            if r.sidewalk_left > 0:
                _lane(left, nl + 1, "sidewalk", r.sidewalk_left)
            for i in range(nl, 0, -1):
                _lane(left, i, "driving", lw)
        ctr = ET.SubElement(sec, "center")
        c0 = ET.SubElement(ctr, "lane", id="0", type="none", level="false")
        ET.SubElement(c0, "roadMark", sOffset="0", type="broken" if nl else "solid",
                      weight="standard", color="yellow", width="0.12")
        right = ET.SubElement(sec, "right")
        for i in range(1, nr + 1):
            _lane(right, -i, "driving", lw, mark=(i == nr))
        if r.sidewalk_right > 0:
            _lane(right, -(nr + 1), "sidewalk", r.sidewalk_right)

        objs = ET.Element("objects")
        for c in m.crossings:
            if c.road != r.id:
                continue
            ET.SubElement(objs, "object", id=c.id, name=c.id, type="crosswalk", dynamic="no",
                          s=_f(c.s - r.trim_start), t="0", zOffset="0", hdg=_f(math.pi / 2),
                          length=_f(c.length), width=_f(c.width), height="0.02", orientation="none")
        sigs = ET.Element("signals")
        for sg in m.signals:
            if sg.road != r.id:
                continue
            s_, t_, _, _ = geo.project_to_polyline(pts, sg.pos)
            ET.SubElement(sigs, "signal", id=sg.id, name=sg.id, s=_f(s_), t=_f(t_), dynamic="yes",
                          orientation="+" if t_ < 0 else "-", zOffset="2.5", country="OpenDRIVE",
                          type="1000001" if sg.kind == "vehicle" else "1000002",
                          subtype="-1", value="-1", height="0.5", width="0.3")
        if len(objs):
            road.append(objs)
        if len(sigs):
            road.append(sigs)

    # ---- junctions: via-centre connecting roads between every legal in/out pair
    next_id = len(m.roads) + 1
    for j in m.junctions:
        jel = ET.Element("junction", id=str(jn_ids[j.id]), name=j.id, type="default")
        info = []
        for rid in j.roads:
            r = m.road(rid)
            at_start = geo.dist(r.pts[0], j.pos) < geo.dist(r.pts[-1], j.pos)
            p = trimmed[r.id][0] if at_start else trimmed[r.id][-1]
            info.append((r, at_start, p))
        cid = 0
        for ra, sa, pa in info:
            nl, nr, lw = _lane_counts(ra)
            if not ((nr > 0 and not sa) or (nl > 0 and sa)):
                continue
            lane_a = -1 if not sa else 1
            for rb, sb, pb in info:
                if rb.id == ra.id:
                    continue
                nl2, nr2, lw2 = _lane_counts(rb)
                if not ((nr2 > 0 and sb) or (nl2 > 0 and not sb)):
                    continue
                lane_b = -1 if sb else 1
                cid += 1
                crid = next_id
                next_id += 1
                pts = [pa, j.pos, pb]
                road = ET.SubElement(root, "road", name=f"{j.id}_{ra.id}_to_{rb.id}", length="0",
                                     id=str(crid), junction=str(jn_ids[j.id]), rule=rule)
                lk = ET.SubElement(road, "link")
                ET.SubElement(lk, "predecessor", elementType="road", elementId=str(byid[ra.id]),
                              contactPoint="start" if sa else "end")
                ET.SubElement(lk, "successor", elementType="road", elementId=str(byid[rb.id]),
                              contactPoint="start" if sb else "end")
                plan = ET.SubElement(road, "planView")
                road.set("length", _f(_add_geometry(plan, pts)))
                lanes = ET.SubElement(road, "lanes")
                sec = ET.SubElement(lanes, "laneSection", s="0", singleSide="false")
                ET.SubElement(ET.SubElement(sec, "center"), "lane", id="0", type="none", level="false")
                ln = ET.SubElement(ET.SubElement(sec, "right"), "lane", id="-1", type="driving", level="false")
                ET.SubElement(ln, "width", sOffset="0", a=_f(min(lw, lw2)), b="0", c="0", d="0")
                ll = ET.SubElement(ln, "link")
                ET.SubElement(ll, "predecessor", id=str(lane_a))
                ET.SubElement(ll, "successor", id=str(lane_b))
                conn = ET.SubElement(jel, "connection", id=str(cid), incomingRoad=str(byid[ra.id]),
                                     connectingRoad=str(crid), contactPoint="start")
                ET.SubElement(conn, "laneLink", **{"from": str(lane_a), "to": "-1"})
        root.append(jel)

    ET.indent(root)
    Path(path).write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode"),
                          encoding="utf-8")
    return byid
