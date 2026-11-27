"""A 30 x 30 m map window: selection, cleaning, local ids and the map text of the prompt. Algorithm notes: ``paper/p1/ALGORITHM.md``.

Everything is derived from the metric ``MapModel``. Nothing is moved: elements are clipped, merged or removed, and every removal is logged.
``localise`` gives the simulator map of a window; the generator does not use it yet.
"""
from __future__ import annotations

import math
import random
from typing import Optional

from .. import geo

SIZE = 30.0
H = SIZE / 2
SIMPLIFY = 0.4                 # m
MIN_LINE = 1.0                 # m, shorter clipped pieces are logged and left out
MIN_AREA = 1.0                 # m2
COVERED = 0.8                  # share of a path lying on road / sidewalk / wider path above which it is merged away
PARALLEL = math.cos(math.radians(30))   # a mapped sidewalk belongs to a road only if their directions differ by less
ROAD_CLEAR = 0.5               # m, an assumed sidewalk centre must stay this far outside any other carriageway
STAIR_GAP = 2.0                # m, stair pieces closer than this form one group
OFF_CARRIAGEWAY = {"tree", "bench", "waste_basket", "street_lamp", "bus_stop", "bicycle_parking"}
KIND_QUOTA = {"crossing": 0.4, "junction": 0.2, "street": 0.25, "pedestrian": 0.15}


# ------------------------------------------------------------------ geometry
def inside(p, eps: float = 1e-6) -> bool:
    return abs(p[0]) <= H + eps and abs(p[1]) <= H + eps


def clip_line(pts) -> list[list]:
    """Pieces of a polyline inside the window (Liang-Barsky per segment)."""
    pieces, cur = [], []
    for a, b in zip(pts, pts[1:]):
        t0, t1, ok = 0.0, 1.0, True
        d = (b[0] - a[0], b[1] - a[1])
        for p, q in ((-d[0], a[0] + H), (d[0], H - a[0]), (-d[1], a[1] + H), (d[1], H - a[1])):
            if p == 0:
                ok &= q >= 0
            elif p < 0:
                t0 = max(t0, q / p)
            else:
                t1 = min(t1, q / p)
        if not ok or t0 >= t1:
            if len(cur) > 1:
                pieces.append(cur)
            cur = []
            continue
        s = (a[0] + t0 * d[0], a[1] + t0 * d[1])
        e = (a[0] + t1 * d[0], a[1] + t1 * d[1])
        if not cur:
            cur = [s]
        cur.append(e)
        if t1 < 1:
            pieces.append(cur)
            cur = []
    if len(cur) > 1:
        pieces.append(cur)
    return pieces


def clip_poly(pts) -> list:
    """Sutherland-Hodgman against the window."""
    out = list(pts)
    for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):
        src, out = out, []
        for i, b in enumerate(src):
            a = src[i - 1]
            ina, inb = sign * a[axis] <= H, sign * b[axis] <= H
            if ina != inb:
                k = (sign * H - a[axis]) / (b[axis] - a[axis])
                out.append((a[0] + k * (b[0] - a[0]), a[1] + k * (b[1] - a[1])))
            if inb:
                out.append(b)
        if not out:
            break
    return out


def simplify(pts) -> list:
    """Drop vertices closer than SIMPLIFY to the line between their neighbours."""
    pts = list(pts)
    i = 1
    while i < len(pts) - 1:
        if geo.dist_to_polyline([pts[i - 1], pts[i + 1]], pts[i]) < SIMPLIFY:
            del pts[i]
        else:
            i += 1
    return pts


def samples(pts, step: float = 0.5) -> list:
    n = max(2, int(geo.polyline_length(pts) / step) + 1)
    length = geo.polyline_length(pts)
    return [geo.point_at(pts, length * i / (n - 1))[0] for i in range(n)]


def hull(points) -> list:
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) > 1 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]

    return half(pts) + half(pts[::-1])


def compass(dx: float, dy: float) -> str:
    return ("east" if dx > 0 else "west") if abs(dx) >= abs(dy) else ("north" if dy > 0 else "south")


def num(v: float) -> str:
    s = f"{v:.1f}"
    s = s[:-2] if s.endswith(".0") else s
    return "0" if s == "-0" else s


def pt(p) -> str:
    return f"({num(p[0])},{num(p[1])})"


def line(pts) -> str:
    return " ".join(pt(p) for p in pts)


def order_key(p) -> tuple:
    """Reading order for local ids: north to south, then west to east."""
    return (-round(p[1], 1), round(p[0], 1))


# ------------------------------------------------------------------ window content
def build(M, centre) -> dict:
    """{'elements': {section: [element]}, 'ids': {local id: source id}, 'removed': [{id, reason}]} for the window at ``centre``."""
    def loc(p):
        return (p[0] - centre[0], p[1] - centre[1])

    removed: list[dict] = []
    ids: dict[str, str] = {}
    count: dict[str, int] = {}

    def new_id(prefix: str, source: str) -> str:
        count[prefix] = count.get(prefix, 0) + 1
        i = f"{prefix}_{count[prefix]}"
        ids[i] = source
        return i

    def drop(source: str, reason: str) -> None:
        removed.append({"id": source, "reason": reason})

    def pieces_of(items) -> list[tuple]:
        out = []
        for o in items:
            for piece in clip_line([loc(p) for p in o.pts]):
                if geo.polyline_length(piece) < MIN_LINE:
                    drop(o.id, "clipped piece shorter than 1 m")
                else:
                    out.append((o, simplify(piece)))
        return sorted(out, key=lambda x: (order_key(x[1][0]), x[0].id))

    # roads and their sidewalks
    roads, road_local = [], {}
    for r, piece in pieces_of(M.roads):
        rid = new_id("road", r.id)
        road_local.setdefault(r.id, []).append((rid, piece))
        walks = []
        full = [loc(p) for p in r.pts]
        for sign, w in ((1, r.sidewalk_left), (-1, r.sidewalk_right)):
            if w <= 0:
                continue
            for side in clip_line(geo.offset_polyline(full, sign * (r.width / 2 + w / 2))):
                side = simplify(side)
                if geo.polyline_length(side) < MIN_LINE:
                    continue
                mid = geo.point_at(side, geo.polyline_length(side) / 2)[0]
                _, _, near, _ = geo.project_to_polyline(full, mid)
                walks.append({"side": compass(mid[0] - near[0], mid[1] - near[1]), "width": w, "line": side})
        roads.append({"id": rid, "src": r.id, "cls": r.hclass, "width": r.width, "lanes": r.lanes, "oneway": r.oneway, "speed": r.speed,
                      "line": piece, "passage": r.passage, "walks": sorted(walks, key=lambda x: x["side"])})

    def road_of(source: Optional[str], p) -> Optional[str]:
        c = road_local.get(source or "")
        return min(c, key=lambda x: geo.dist_to_polyline(x[1], p))[0] if c else None

    # junctions and road ends
    junctions = []
    for j in sorted(M.junctions, key=lambda j: order_key(loc(j.pos))):
        p = loc(j.pos)
        if inside(p):
            met = sorted({road_of(s, p) for s in j.roads if road_of(s, p)}, key=lambda i: int(i.split("_")[1]))
            junctions.append({"id": new_id("junction", j.id), "pos": p, "radius": j.radius, "roads": met, "signalised": j.signalized})
    for r in roads:
        ends = []
        for k in (0, -1):
            p = r["line"][k]
            q = r["line"][1 if k == 0 else -2]
            heading = compass(p[0] - q[0], p[1] - q[1])
            near = [j for j in junctions if geo.dist(p, j["pos"]) <= j["radius"] + 1.0]
            joined = [o["id"] for o in roads if o is not r and min(geo.dist(p, o["line"][0]), geo.dist(p, o["line"][-1])) <= 0.6]
            if max(abs(p[0]), abs(p[1])) >= H - 0.1:
                what = "leaves the window"
            elif near:
                what = f"at {near[0]['id']}"
            elif joined:
                what = "continues as " + ", ".join(joined)
            else:
                what = "road ends"
            ends.append(f"{heading} end {what}")
        r["ends"] = ends

    # paths: stairs are grouped, covered paths are merged away
    stairs_raw = [(o, p) for o, p in pieces_of([x for x in M.paths if x.ptype == "steps"])]
    groups: list[list] = []
    for o, p in stairs_raw:
        near = [g for g in groups if any(geo.dist(a, b) <= STAIR_GAP for _, q in g for a in samples(p) for b in samples(q))]
        merged = [(o, p)] + [x for g in near for x in g]
        groups = [g for g in groups if g not in near] + [merged]
    stairs = []
    for g in sorted(groups, key=lambda g: min(order_key(q) for _, p in g for q in p)):
        corners = []
        for o, p in g:
            for sign in (1, -1):
                corners += [(min(H, max(-H, x)), min(H, max(-H, y))) for x, y in geo.offset_polyline(p, sign * o.width / 2)]
        sid = new_id("stairs", "+".join(sorted({o.id for o, _ in g})))
        stairs.append({"id": sid, "outline": simplify(hull(corners)), "parts": len(g)})
    walks = []                                          # assumed strips, cut where they would lie on another road
    for r in roads:
        for w in r["walks"]:
            src = f"{r['src']}:{w['side']}"
            parts, cur = [], []
            for q in samples(w["line"], 0.25):
                if any(o is not r and geo.dist_to_polyline(o["line"], q) <= o["width"] / 2 + ROAD_CLEAR for o in roads):
                    parts.append(cur)
                    cur = []
                else:
                    cur.append(q)
            parts.append(cur)
            if len(parts) == 1:
                kept_parts = [w["line"]]
            else:
                drop(src, "part of an assumed sidewalk lies on another road (cut)")
                kept_parts = [simplify(c) for c in parts if len(c) > 1 and geo.polyline_length(c) >= MIN_LINE]
            walks += [{"road": r["id"], **w, "line": c, "source": "assumed", "src": src} for c in kept_parts]
    mapped = []
    for o, p in pieces_of([x for x in M.paths if x.ptype == "sidewalk"]):
        mid = geo.point_at(p, geo.polyline_length(p) / 2)[0]
        on = [any(geo.dist_to_polyline(r["line"], q) <= r["width"] / 2 for r in roads) for q in samples(p)]
        if sum(on) / len(on) >= COVERED:
            drop(o.id, "mapped sidewalk lies on a road")
            continue
        heading = geo.project_to_polyline(p, mid)[3]
        beside = [r for r in roads if geo.dist_to_polyline(r["line"], mid) <= r["width"] / 2 + 8.0
                  and abs(math.cos(geo.project_to_polyline(r["line"], mid)[3] - heading)) >= PARALLEL]
        road, side = None, ""
        if beside:                                       # named after the nearest road that runs in the same direction
            near = min(beside, key=lambda r: geo.dist_to_polyline(r["line"], mid))
            foot = geo.project_to_polyline(near["line"], mid)[2]
            road, side = near["id"], compass(mid[0] - foot[0], mid[1] - foot[1])
        mapped.append({"road": road, "side": side, "width": o.width, "line": p, "source": "mapped", "src": o.id, "passage": o.passage})
    walks = sorted(walks + mapped, key=lambda w: (order_key(w["line"][0]), w["src"]))
    for w in walks:
        w["id"] = new_id("sidewalk", w["src"])
    paths, kept = [], []
    for o, p in sorted(pieces_of([x for x in M.paths if x.ptype not in ("steps", "sidewalk")]), key=lambda x: (-x[0].width, order_key(x[1][0]), x[0].id)):
        def covered(q) -> bool:
            on_street = any(geo.dist_to_polyline(r["line"], q) <= r["width"] / 2 for r in roads) or \
                any(geo.dist_to_polyline(w["line"], q) <= w["width"] / 2 for w in walks)
            return on_street or any(geo.dist_to_polyline(k, q) <= width / 2 for k, width in kept)
        pts = samples(p)
        if sum(map(covered, pts)) / len(pts) >= COVERED:
            drop(o.id, "path lies on a road, sidewalk or wider path (merged)")
            continue
        kept.append((p, o.width))
        paths.append({"src": o.id, "type": o.ptype, "width": o.width, "line": p, "passage": o.passage})
    paths.sort(key=lambda x: order_key(x["line"][0]))
    for x in paths:
        x["id"] = new_id("path", x["src"])

    # crossings and signals
    signals, signal_local = [], {}
    for s in sorted(M.signals, key=lambda s: order_key(loc(s.pos))):
        if inside(loc(s.pos)):
            signal_local[s.id] = new_id("signal", s.id)
            signals.append({"id": signal_local[s.id], "src": s.id, "kind": s.kind, "pos": loc(s.pos), "crossing_src": s.crossing})
    crossings, crossing_local = [], {}
    for c in sorted(M.crossings, key=lambda c: order_key(loc(c.pos))):
        a, b = (loc(p) for p in c.endpoints())
        part = clip_line([a, b])
        if not part:
            continue
        if not inside(loc(c.pos)):
            drop(c.id, "crossing centre outside the window")
            continue
        crossing_local[c.id] = new_id("crossing", c.id)
        sig = None
        if c.signal_id:
            sig = signal_local.get(c.signal_id) or new_id("signal", c.signal_id)       # a signal may stand just outside the window
            signal_local[c.signal_id] = sig
        crossings.append({"id": crossing_local[c.id], "control": c.control, "road": road_of(c.road, loc(c.pos)), "width": c.width,
                          "line": part[0], "signal": sig})
    for s in signals:
        s["crossing"] = crossing_local.get(s["crossing_src"] or "")

    # objects: never moved; implausible ones are removed and logged
    objects = []
    for o in sorted(M.props, key=lambda o: (o.ptype, order_key(loc(o.pos)))):
        p = loc(o.pos)
        if not inside(p):
            continue
        surface = M.surface_at(o.pos)
        if surface in ("building", "water"):
            drop(o.id, f"object inside {surface}")
        elif o.ptype in OFF_CARRIAGEWAY and surface in ("road", "crosswalk"):
            drop(o.id, f"{o.ptype} on the {surface}")
        elif any(x["type"] == o.ptype and geo.dist(x["pos"], p) < 0.3 for x in objects):
            drop(o.id, "duplicate object at the same spot")
        else:
            objects.append({"id": new_id(o.ptype, o.id), "src": o.id, "type": o.ptype, "pos": p})

    def polygons(items, prefix) -> list:
        out = []
        for it in items:
            c = clip_poly([loc(p) for p in it.pts])
            if len(c) < 3:
                continue
            c = simplify(c + c[:1])[:-1]
            if len(c) < 3 or abs(geo.polygon_area(c)) < MIN_AREA:
                drop(it.id, "clipped area smaller than 1 m2")
                continue
            out.append((it, c))
        return [{"id": new_id(prefix, it.id), "src": it.id, "type": getattr(it, "atype", ""), "outline": c,
                 "holes": [h for h in (clip_poly([loc(p) for p in q]) for q in getattr(it, "holes", [])) if len(h) >= 3]}
                for it, c in sorted(out, key=lambda x: (order_key(geo.polygon_centroid(x[1])), x[0].id))]

    buildings = polygons(M.buildings, "building")
    areas = polygons(M.areas, "area")
    barriers = [{"id": new_id("barrier", o.id), "src": o.id, "type": o.btype, "line": p} for o, p in pieces_of(M.barriers)]
    return {"elements": {"roads": roads, "sidewalks": walks, "junctions": junctions, "crossings": crossings, "signals": signals, "paths": paths, "stairs": stairs,
                         "objects": objects, "buildings": buildings, "areas": areas, "barriers": barriers},
            "ids": ids, "removed": removed}


# ------------------------------------------------------------------ the window as a simulator map
def localise(M, window: dict, centre):
    """A copy of the whole map in the window frame, with the window's local ids.

    Geometry outside the window is kept (cars start there, the simulator shows it); elements without a local id are named ``out_<source id>``.
    """
    from ..mapmodel import MapModel

    d = M.to_dict()
    d.pop("ped_graph", None)
    cx, cy = centre

    def p(q):
        return [q[0] - cx, q[1] - cy]

    def many(q):
        return [p(x) for x in q]

    first: dict[str, str] = {}           # source id -> the id the element gets
    extra: dict[str, str] = {}           # further local ids of the same element
    strips: dict[str, list] = {}         # local id -> [source road, side]
    for local, source in window["ids"].items():
        if ":" in source:                # assumed sidewalk "<road>:<compass side>"
            road, side = source.rsplit(":", 1)
            r = M.road(road)
            heading = geo.project_to_polyline(r.pts, centre)[3]
            left = compass(-math.sin(heading), math.cos(heading))
            strips[local] = [road, 1 if side == left else -1]
            continue
        for k, s in enumerate(source.split("+")):          # a stair group has several sources
            if s not in first and k == 0:
                first[s] = local
            else:
                extra[local if k == 0 else f"{local}_{k + 1}"] = s

    def name(s):
        return None if s is None else first.get(s, f"out_{s}")

    for key in ("roads", "junctions", "crossings", "signals", "props", "buildings", "barriers", "areas", "paths", "railways"):
        for o in d[key]:
            o["id"] = name(o["id"])
            for field in ("pts", "polygon"):
                if field in o:
                    o[field] = many(o[field])
            if "pos" in o:
                o["pos"] = p(o["pos"])
            if "corners" in o:
                o["corners"] = [many(c) for c in o["corners"]]
            if "holes" in o:
                o["holes"] = [many(h) for h in o["holes"]]
            for field in ("road", "signal_id", "crossing"):
                if o.get(field):
                    o[field] = name(o[field])
            if key == "junctions":
                o["roads"] = [name(r) for r in o["roads"]]
    d["aliases"] = {**{local: name(s) for local, s in extra.items()}, **{local: [name(r), side] for local, (r, side) in strips.items()}}
    lat, lon = M.proj.to_latlon(cx, cy)
    d["origin"] = {"lat": lat, "lon": lon}
    x0, y0, x1, y1 = M.bounds
    d["bounds"] = [x0 - cx, y0 - cy, x1 - cx, y1 - cy]
    return MapModel.from_dict(d)


# ------------------------------------------------------------------ text
UNDER = ", passes under a building"


def to_text(window: dict) -> str:
    e = window["elements"]
    out = ["# MAP",
           "size: 30 x 30 m",
           "frame: origin at the centre; x grows east, y grows north; metres; x and y in [-15, 15]"]

    def section(title: str, rows: list[str]) -> None:
        out.append("")
        out.append(f"## {title}")
        out.extend(rows or ["none"])

    rows = []
    for r in e["roads"]:
        traffic = "one-way, in the listed point order" if r["oneway"] else "two-way"
        rows.append(f"{r['id']}: {r['cls']}, width {num(r['width'])}, lanes {r['lanes']}, {traffic}, speed limit {num(r['speed'])} m/s" + (UNDER if r["passage"] else ""))
        rows.append(f"  centre line: {line(r['line'])}")
        rows.append(f"  ends: {'; '.join(r['ends'])}")
    section("ROADS", rows)
    section("SIDEWALKS", [f"{w['id']}: " + (f"{w['side']} of {w['road']}, " if w["road"] else "") + f"width {num(w['width'])}, centre line {line(w['line'])}" + (UNDER if w.get("passage") else "")
                          for w in e["sidewalks"]])
    section("JUNCTIONS", [f"{j['id']}: at {pt(j['pos'])}, radius {num(j['radius'])}, joins {', '.join(j['roads']) or 'none'}"
                          + (", signalised" if j["signalised"] else "") for j in e["junctions"]])
    section("CROSSINGS", [f"{c['id']}: {c['control']}" + (f", over {c['road']}" if c["road"] else "") + f", width {num(c['width'])}, "
                          f"kerb to kerb {line(c['line'])}" + (f", signal {c['signal']}" if c["signal"] else "") for c in e["crossings"]])
    section("SIGNALS", [f"{s['id']}: {s['kind']} light at {pt(s['pos'])}" + (f", for {s['crossing']}" if s["crossing"] else "") for s in e["signals"]])
    section("PATHS", [f"{p['id']}: {p['type']}, width {num(p['width'])}, centre line {line(p['line'])}" + (UNDER if p["passage"] else "") for p in e["paths"]])
    section("STAIRS", [f"{s['id']}: area {line(s['outline'])}" for s in e["stairs"]])
    by_type: dict[str, list] = {}
    for o in e["objects"]:
        by_type.setdefault(o["type"], []).append(f"{o['id']} {pt(o['pos'])}")
    section("OBJECTS", [f"{t}: {'; '.join(v)}" for t, v in by_type.items()])
    section("BUILDINGS", [f"{b['id']}: outline {line(b['outline'])}" + "".join(f", courtyard {line(h)}" for h in b["holes"]) for b in e["buildings"]])
    section("AREAS", [f"{a['id']}: {a['type']}, outline {line(a['outline'])}" for a in e["areas"]])
    section("BARRIERS", [f"{b['id']}: {b['type']}, line {line(b['line'])}" for b in e["barriers"]])
    return "\n".join(out)


# ------------------------------------------------------------------ selection
def candidates(M) -> dict[str, list]:
    """Anchor points per window kind."""
    out = {"crossing": [c.pos for c in M.crossings], "junction": [j.pos for j in M.junctions], "street": [], "pedestrian": []}
    for r in M.roads:
        if r.length >= SIZE:
            out["street"] += [geo.point_at(r.pts, s)[0] for s in range(int(H), int(r.length - H) + 1, int(H))]
    for p in M.paths:
        if p.ptype in ("pedestrian", "footway", "path"):
            out["pedestrian"] += samples(p.pts, H)
    return out


def kind_fits(M, kind: str, c) -> bool:
    near = lambda p: abs(p[0] - c[0]) <= H and abs(p[1] - c[1]) <= H
    has_crossing = any(near(x.pos) for x in M.crossings)
    has_junction = any(near(x.pos) for x in M.junctions)
    if kind == "street":
        return not has_crossing and not has_junction
    if kind == "pedestrian":
        return not has_crossing and not any(clip_line([(p[0] - c[0], p[1] - c[1]) for p in r.pts]) for r in M.roads)
    return True


def walkable_share(M, c, n: int = 10) -> float:
    cells = [(c[0] - H + SIZE * (i + 0.5) / n, c[1] - H + SIZE * (j + 0.5) / n) for i in range(n) for j in range(n)]
    return sum(M.surface_at(p) in ("sidewalk", "path", "crosswalk") for p in cells) / len(cells)


def select(M, n: int, seed: int = 0, jitter: float = 6.0, spacing: float = 20.0, min_walk: float = 0.05) -> list[tuple[str, tuple]]:
    """Up to ``n`` (kind, centre) windows with the quotas of KIND_QUOTA: random anchor, random offset (so the anchor is not always central),
    kind condition, enough walkable surface, centres at least ``spacing`` apart."""
    rng = random.Random(seed)
    cand = candidates(M)
    for v in cand.values():
        rng.shuffle(v)
    chosen: list[tuple[str, tuple]] = []
    for kind, share in KIND_QUOTA.items():
        want, got = math.ceil(n * share), 0
        for a in cand[kind]:
            if got >= want or len(chosen) >= n:
                break
            c = (a[0] + rng.uniform(-jitter, jitter), a[1] + rng.uniform(-jitter, jitter))
            if any(max(abs(c[0] - o[0]), abs(c[1] - o[1])) < spacing for _, o in chosen):
                continue
            if kind_fits(M, kind, c) and walkable_share(M, c) >= min_walk:
                chosen.append((kind, c))
                got += 1
    return chosen
