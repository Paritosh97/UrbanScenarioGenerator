"""OSM XML -> MapModel, plus an offline-friendly Overpass fetcher."""
from __future__ import annotations

import hashlib
import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Optional

from . import geo
from .geo import Pt
from .mapmodel import (Area, Barrier, Building, Crossing, Junction, MapModel, Path as PathF, Prop,
                       Railway, Road, Signal, CAR_CLASSES, DEFAULT_SIDEWALK_W, LANE_W,
                       SIDEWALK_DEFAULT_CLASSES, SPEED_DEFAULT)

PATH_CLASSES = {"footway", "path", "pedestrian", "cycleway", "steps", "track"}
OVERPASS = "https://overpass-api.de/api/interpreter"


# ------------------------------------------------------------------ fetch
def bbox_from_center(lat: float, lon: float, size_m: float) -> tuple[float, float, float, float]:
    """(min_lat, min_lon, max_lat, max_lon) of a square of side ``size_m`` metres around a point."""
    d_lat = (size_m / 2) / 111_320
    d_lon = (size_m / 2) / (111_320 * math.cos(math.radians(lat)))
    return (lat - d_lat, lon - d_lon, lat + d_lat, lon + d_lon)


def bbox_area_km2(b: tuple[float, float, float, float]) -> float:
    h = (b[2] - b[0]) * 111.32
    w = (b[3] - b[1]) * 111.32 * math.cos(math.radians((b[0] + b[2]) / 2))
    return abs(h * w)


def fetch_osm(min_lat: float, min_lon: float, max_lat: float, max_lon: float,
              cache_dir: str | Path = ".usg_cache", endpoint: str = OVERPASS) -> Path:
    """Download (once) the OSM extract for a bbox. Cached on disk so later runs are offline."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{min_lat},{min_lon},{max_lat},{max_lon}".encode()).hexdigest()[:12]
    out = cache / f"osm_{key}.osm"
    if out.exists():
        return out
    bb = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    q = f"""[out:xml][timeout:90];
(way["highway"]({bb});way["building"]({bb});way["barrier"]({bb});way["railway"]({bb});
 way["natural"="water"]({bb});way["leisure"~"park|garden"]({bb});way["landuse"~"grass|forest"]({bb});
 node["highway"]({bb});node["amenity"~"waste_basket|bench|bicycle_parking"]({bb});
 node["natural"="tree"]({bb});node["public_transport"]({bb});node["barrier"="bollard"]({bb}););
(._;>;);out;"""
    req = urllib.request.Request(endpoint, data=urllib.parse.urlencode({"data": q}).encode(),
                                 headers={"User-Agent": "usg/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out.write_bytes(r.read())
    return out


# ------------------------------------------------------------------ parse
class _Osm:
    def __init__(self):
        self.nodes: dict[int, tuple[float, float, dict]] = {}
        self.ways: dict[int, tuple[list[int], dict]] = {}


def parse_osm(src: str | Path) -> _Osm:
    text = Path(src).read_text(encoding="utf-8") if not str(src).lstrip().startswith("<") else str(src)
    root = ET.fromstring(text)
    o = _Osm()
    for n in root.iter("node"):
        tags = {t.get("k"): t.get("v") for t in n.findall("tag")}
        o.nodes[int(n.get("id"))] = (float(n.get("lat")), float(n.get("lon")), tags)
    for w in root.iter("way"):
        tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
        refs = [int(nd.get("ref")) for nd in w.findall("nd")]
        o.ways[int(w.get("id"))] = (refs, tags)
    return o


def _num(s: Optional[str], default: float) -> float:
    if not s:
        return default
    m = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", s)
    return float(m.group(1)) if m else default


def _speed(tags: dict, hclass: str) -> float:
    ms = tags.get("maxspeed")
    if ms:
        v = _num(ms, 0)
        if v > 0:
            return v * (0.44704 if "mph" in ms else 1 / 3.6)
    return SPEED_DEFAULT.get(hclass, 8.3)


def _sidewalk_widths(tags: dict, hclass: str, default_sidewalks: bool, width: float) -> tuple[float, float]:
    sw = tags.get("sidewalk")
    left = right = 0.0
    if sw in ("both", "yes"):
        left = right = DEFAULT_SIDEWALK_W
    elif sw == "left":
        left = DEFAULT_SIDEWALK_W
    elif sw == "right":
        right = DEFAULT_SIDEWALK_W
    elif sw in ("no", "none", "separate"):
        pass
    elif default_sidewalks and hclass in SIDEWALK_DEFAULT_CLASSES:
        left = right = DEFAULT_SIDEWALK_W
    if tags.get("sidewalk:left") in ("yes", "both"):
        left = DEFAULT_SIDEWALK_W
    if tags.get("sidewalk:right") in ("yes", "both"):
        right = DEFAULT_SIDEWALK_W
    if tags.get("sidewalk:both") in ("yes",):
        left = right = DEFAULT_SIDEWALK_W
    return left, right


# ------------------------------------------------------------------ build
def build_map(osm: _Osm | str | Path, bbox: Optional[tuple[float, float, float, float]] = None,
              default_sidewalks: bool = True) -> MapModel:
    """Project once, build the metric model, derive junctions/crossings/props."""
    if not isinstance(osm, _Osm):
        osm = parse_osm(osm)
    if bbox:
        lat0, lon0 = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    else:
        lats = [n[0] for n in osm.nodes.values()]
        lons = [n[1] for n in osm.nodes.values()]
        lat0, lon0 = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    proj = geo.Projection(lat0, lon0)
    m = MapModel(proj)
    xy = {nid: proj.to_xy(n[0], n[1]) for nid, n in osm.nodes.items()}

    def way_pts(refs):
        return [xy[r] for r in refs if r in xy]

    # ---- road ways -> split into graph edges at shared nodes
    road_ways = {wid: (refs, t) for wid, (refs, t) in osm.ways.items()
                 if t.get("highway") in CAR_CLASSES and len(refs) >= 2
                 and t.get("area") != "yes"}
    use = defaultdict(int)
    for wid, (refs, _) in road_ways.items():
        for i, r in enumerate(refs):
            use[r] += 2 if i in (0, len(refs) - 1) else 1
    node_deg: dict[int, int] = defaultdict(int)
    n_roads = 0
    for wid in sorted(road_ways):
        refs, t = road_ways[wid]
        hclass = t["highway"]
        oneway = t.get("oneway") in ("yes", "true", "1") or hclass in ("motorway",)
        lanes = int(_num(t.get("lanes"), 1 if (oneway or hclass == "service") else 2))
        width = _num(t.get("width"), lanes * LANE_W if hclass != "service" else 4.0)
        if hclass == "service" and "lanes" not in t and "width" not in t:
            lanes = 1
        swl, swr = _sidewalk_widths(t, hclass, default_sidewalks, width)
        cuts = [0] + [i for i in range(1, len(refs) - 1) if use[refs[i]] >= 2] + [len(refs) - 1]
        for a, b in zip(cuts[:-1], cuts[1:]):
            seg = refs[a:b + 1]
            pts = way_pts(seg)
            if len(pts) < 2 or geo.polyline_length(pts) < 0.5:
                continue
            n_roads += 1
            m.roads.append(Road(id=f"road_{n_roads}", osm_way=wid, name=t.get("name", ""),
                                hclass=hclass, pts=pts, lanes=lanes, width=width, oneway=oneway,
                                speed=_speed(t, hclass), sidewalk_left=swl, sidewalk_right=swr,
                                start_node=f"n{seg[0]}", end_node=f"n{seg[-1]}"))
            node_deg[seg[0]] += 1
            node_deg[seg[-1]] += 1

    # ---- junctions (degree >= 3), trimming
    incident: dict[str, list[tuple[Road, bool]]] = defaultdict(list)
    for r in m.roads:
        incident[r.start_node].append((r, True))
        incident[r.end_node].append((r, False))
    jn = 0
    for node, lst in incident.items():
        if len(lst) < 3:
            continue
        jn += 1
        nid = int(node[1:])
        pos = xy[nid]
        radius = max(r.width / 2 + max(r.sidewalk_left, r.sidewalk_right) for r, _ in lst) + 2.0
        j = Junction(id=f"junction_{jn}", pos=pos, roads=[r.id for r, _ in lst], radius=radius)
        m.junctions.append(j)
        for r, is_start in lst:
            trim = min(radius, r.length * 0.45)
            if is_start:
                r.trim_start = trim
            else:
                r.trim_end = trim

    # ---- signals
    sig_n = 0
    for nid, (lat, lon, t) in osm.nodes.items():
        if t.get("highway") == "traffic_signals" or t.get("crossing") == "traffic_signals":
            sig_n += 1
            rd, s, tt, d = m.nearest_road(xy[nid])
            kind = "pedestrian" if t.get("highway") == "crossing" else "vehicle"
            m.signals.append(Signal(id=f"signal_{sig_n}", pos=xy[nid], road=rd.id if rd else None,
                                    kind=kind))

    # ---- crossings
    cr_n = 0

    def add_crossing(p: Pt, tags: dict, hdg_hint: Optional[float] = None):
        nonlocal cr_n
        rd, s, tt, d = m.nearest_road(p)
        if rd is None or d > rd.width / 2 + 4.0:
            return
        s = max(rd.trim_start + 1.5 + 1.5, min(rd.length - rd.trim_end - 3.0, s))
        cp, h = geo.point_at(rd.pts, s)
        for c in m.crossings:
            if geo.dist(c.pos, cp) < 4.0:
                return
        ctl = tags.get("crossing", "")
        near_sig = min(m.signals, key=lambda sg: geo.dist(sg.pos, cp), default=None)
        signal_id = None
        if ctl in ("traffic_signals",) or tags.get("crossing_ref") == "pelican" or (
                near_sig and geo.dist(near_sig.pos, cp) < 18 and tags.get("highway") == "crossing"
                and ctl != "zebra"):
            control, signal_id = "signals", (near_sig.id if near_sig else None)
        elif ctl in ("zebra", "marked") or tags.get("crossing_ref") == "zebra":
            control = "zebra"
        else:
            control = "uncontrolled"
        cr_n += 1
        m.crossings.append(Crossing(id=f"crossing_{cr_n}", road=rd.id, s=s, pos=cp,
                                    heading=geo.wrap_pi(h + math.pi / 2), length=rd.width,
                                    width=3.0, control=control, signal_id=signal_id))

    for nid, (lat, lon, t) in osm.nodes.items():
        if t.get("highway") == "crossing" or t.get("railway") == "crossing":
            add_crossing(xy[nid], t)
    for wid, (refs, t) in osm.ways.items():
        if t.get("highway") == "footway" and t.get("footway") == "crossing" and len(refs) >= 2:
            pts = way_pts(refs)
            add_crossing(geo.point_at(pts, geo.polyline_length(pts) / 2)[0], t)

    # link crossing signals back
    for c in m.crossings:
        if c.signal_id:
            for sg in m.signals:
                if sg.id == c.signal_id:
                    sg.crossing = c.id

    # junction signalisation
    for j in m.junctions:
        near = [s for s in m.signals if s.kind == "vehicle" and geo.dist(s.pos, j.pos) < j.radius + 15]
        if near:
            j.signalized, j.signal_id = True, near[0].id

    # ---- props
    pr_n = 0

    def add_prop(ptype: str, p: Pt, tags: dict, align: bool):
        nonlocal pr_n
        pr_n += 1
        rd, s, tt, d = m.nearest_road(p)
        hdg = 0.0
        if rd is not None:
            _, _, _, rh = geo.project_to_polyline(rd.pts, p)
            hdg = rh
            if align and tt < 0:      # on the right side: face the road (paper alg. 1)
                hdg = geo.wrap_pi(rh + math.pi / 2)
            elif align:
                hdg = geo.wrap_pi(rh - math.pi / 2)
        m.props.append(Prop(id=f"{ptype}_{pr_n}", ptype=ptype, pos=p, heading=hdg,
                            road=rd.id if rd else None, name=tags.get("name", "")))

    for nid, (lat, lon, t) in sorted(osm.nodes.items()):
        p = xy[nid]
        if t.get("highway") == "bus_stop" or t.get("public_transport") in ("platform", "stop_position") \
                and t.get("bus") == "yes":
            add_prop("bus_stop", p, t, True)
        elif t.get("amenity") == "waste_basket":
            add_prop("waste_basket", p, t, False)
        elif t.get("amenity") == "bench":
            add_prop("bench", p, t, True)
        elif t.get("natural") == "tree":
            add_prop("tree", p, t, False)
        elif t.get("highway") == "street_lamp":
            add_prop("street_lamp", p, t, False)
        elif t.get("barrier") == "bollard":
            add_prop("bollard", p, t, False)
        elif t.get("amenity") == "bicycle_parking":
            add_prop("bicycle_parking", p, t, True)

    # ---- polygons / lines
    b_n = bar_n = a_n = p_n = rw_n = 0
    for wid, (refs, t) in sorted(osm.ways.items()):
        pts = way_pts(refs)
        closed = len(refs) > 3 and refs[0] == refs[-1]
        if "building" in t and closed and len(pts) >= 4:
            poly = pts[:-1]
            if geo.polygon_area(poly) < 0:
                poly.reverse()
            h = _num(t.get("height"), 0) or _num(t.get("building:levels"), 3) * 3.0
            b_n += 1
            m.buildings.append(Building(id=f"building_{b_n}", pts=poly, height=max(3.0, h),
                                        name=t.get("name", "")))
        elif "barrier" in t and t["barrier"] in ("fence", "wall", "hedge", "guard_rail", "retaining_wall",
                                                   "city_wall") and len(pts) >= 2:
            bar_n += 1
            m.barriers.append(Barrier(id=f"barrier_{bar_n}", pts=pts,
                                      height=_num(t.get("height"), 1.2), btype=t["barrier"]))
        elif (t.get("natural") == "water" or t.get("waterway") == "riverbank") and closed:
            a_n += 1
            m.areas.append(Area(id=f"water_{a_n}", atype="water", pts=pts[:-1]))
        elif (t.get("leisure") in ("park", "garden") or t.get("landuse") in ("grass", "forest")
              or t.get("natural") == "wood") and closed:
            a_n += 1
            m.areas.append(Area(id=f"green_{a_n}", atype="green", pts=pts[:-1]))
        elif t.get("highway") in PATH_CLASSES and t.get("footway") != "crossing" and len(pts) >= 2 \
                and t.get("footway") != "sidewalk":
            p_n += 1
            m.paths.append(PathF(id=f"path_{p_n}", pts=pts,
                                 width=_num(t.get("width"), 6.0 if t["highway"] == "pedestrian" else 2.0),
                                 ptype=t["highway"]))
        elif "railway" in t and t["railway"] in ("rail", "tram", "light_rail", "subway") and len(pts) >= 2:
            rw_n += 1
            m.railways.append(Railway(id=f"railway_{rw_n}", pts=pts, rtype=t["railway"]))

    _junction_geometry(m)
    xs = [p[0] for r in m.roads for p in r.pts] + [p[0] for b in m.buildings for p in b.pts] or [0.0]
    ys = [p[1] for r in m.roads for p in r.pts] + [p[1] for b in m.buildings for p in b.pts] or [0.0]
    m.bounds = (min(xs), min(ys), max(xs), max(ys))
    m.reindex()
    return m


def _junction_geometry(m: MapModel) -> None:
    """Asphalt polygon + sidewalk corner patches per junction (computed once, used by the web renderer)."""
    byid = {r.id: r for r in m.roads}
    for j in m.junctions:
        ends = []
        for rid in j.roads:
            r = byid[rid]
            at_start = geo.dist(r.pts[0], j.pos) < geo.dist(r.pts[-1], j.pos)
            trim = r.trim_start if at_start else r.trim_end
            s = trim if at_start else r.length - trim
            p, h = geo.point_at(r.pts, s)
            out_h = h if at_start else geo.wrap_pi(h + math.pi)      # pointing away from junction
            nl = (-math.sin(out_h), math.cos(out_h))                 # left of outward direction
            ends.append((out_h, r, p, nl, at_start))
        ends.sort(key=lambda e: e[0])
        ring, corners = [], []
        for k, (h, r, p, nl, at_start) in enumerate(ends):
            half = r.width / 2
            ring.append((p[0] - nl[0] * half, p[1] - nl[1] * half))   # right edge
            ring.append((p[0] + nl[0] * half, p[1] + nl[1] * half))   # left edge
        j.polygon = ring
        for k in range(len(ends)):
            h1, r1, p1, n1, s1 = ends[k]
            h2, r2, p2, n2, s2 = ends[(k + 1) % len(ends)]
            # CCW neighbour: left side of end k meets right side of end k+1
            sw1 = (r1.sidewalk_right if not s1 else r1.sidewalk_left)
            sw2 = (r2.sidewalk_left if not s2 else r2.sidewalk_right)
            w = max(sw1, sw2)
            if w <= 0:
                continue
            a = (p1[0] + n1[0] * r1.width / 2, p1[1] + n1[1] * r1.width / 2)
            a2 = (p1[0] + n1[0] * (r1.width / 2 + w), p1[1] + n1[1] * (r1.width / 2 + w))
            b = (p2[0] - n2[0] * r2.width / 2, p2[1] - n2[1] * r2.width / 2)
            b2 = (p2[0] - n2[0] * (r2.width / 2 + w), p2[1] - n2[1] * (r2.width / 2 + w))
            corners.append([a, a2, b2, b])
        j.corners = corners
