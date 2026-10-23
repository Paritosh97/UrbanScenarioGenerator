"""Pedestrian routing graph (sidewalks + crossings + paths) for grounding and feasibility checks."""
from __future__ import annotations

import heapq
import math
from typing import TYPE_CHECKING, Optional

from . import geo
from .geo import Pt

if TYPE_CHECKING:
    from .mapmodel import MapModel

STEP = 12.0
CROSSING_PENALTY = 4.0          # metres-equivalent cost added per crossing (prefers fewer crossings)


class PedGraph:
    def __init__(self):
        self.nodes: dict[str, Pt] = {}
        self.adj: dict[str, list[tuple[str, float, str, Optional[str]]]] = {}   # n -> (m, w, kind, ref)

    # ---------------------------------------------------------------- build
    def _node(self, key: str, p: Pt) -> str:
        if key not in self.nodes:
            self.nodes[key] = p
            self.adj[key] = []
        return key

    def _edge(self, a: str, b: str, kind: str = "walk", ref: Optional[str] = None) -> None:
        if a == b:
            return
        w = geo.dist(self.nodes[a], self.nodes[b])
        self.adj[a].append((b, w, kind, ref))
        self.adj[b].append((a, w, kind, ref))

    @staticmethod
    def build(m: "MapModel") -> "PedGraph":
        g = PedGraph()
        side_lines: dict[tuple[str, int], list[tuple[float, str]]] = {}
        end_nodes: dict[tuple[str, int, bool], str] = {}      # (road, side, at_start) -> node

        for r in m.roads:
            lo, hi = r.trim_start, r.length - r.trim_end
            for side, w in ((+1, r.sidewalk_left), (-1, r.sidewalk_right)):
                width = w if w > 0 else 1.0                   # implicit verge for routing only
                off = side * (r.width / 2 + width / 2)
                c = geo.offset_polyline(r.pts, off)
                ss = sorted({lo, hi, *[lo + (hi - lo) * i / max(1, round((hi - lo) / STEP))
                                       for i in range(1, max(1, round((hi - lo) / STEP)))]})
                for cr in m.crossings:
                    if cr.road == r.id and lo < cr.s < hi:
                        ss.append(cr.s)
                ss = sorted(set(round(s, 3) for s in ss))
                chain = []
                for s in ss:
                    p, _ = geo.point_at(c, s)
                    nid = g._node(f"{r.id}:{'L' if side > 0 else 'R'}:{s:.2f}", p)
                    chain.append((s, nid))
                for (s0, a), (s1, b) in zip(chain[:-1], chain[1:]):
                    g._edge(a, b, "sidewalk" if w > 0 else "verge", f"sidewalk_{r.id}_{'left' if side > 0 else 'right'}")
                side_lines[(r.id, side)] = chain
                end_nodes[(r.id, side, True)] = chain[0][1]
                end_nodes[(r.id, side, False)] = chain[-1][1]

        for cr in m.crossings:
            L, R = side_lines.get((cr.road, +1)), side_lines.get((cr.road, -1))
            if not L or not R:
                continue
            a = min(R, key=lambda t: abs(t[0] - cr.s))[1]
            b = min(L, key=lambda t: abs(t[0] - cr.s))[1]
            g._edge(a, b, "crossing", cr.id)

        byid = {r.id: r for r in m.roads}
        for j in m.junctions:
            ends = []
            for rid in j.roads:
                r = byid[rid]
                at_start = geo.dist(r.pts[0], j.pos) < geo.dist(r.pts[-1], j.pos)
                p, h = geo.point_at(r.pts, r.trim_start if at_start else r.length - r.trim_end)
                ends.append((h if at_start else geo.wrap_pi(h + math.pi), r, at_start))
            ends.sort(key=lambda e: e[0])
            for k in range(len(ends)):
                _, r1, s1 = ends[k]
                _, r2, s2 = ends[(k + 1) % len(ends)]
                left1 = +1 if s1 else -1            # left of outward direction
                right2 = -1 if s2 else +1
                a = end_nodes[(r1.id, left1, s1)]
                b = end_nodes[(r2.id, right2, s2)]
                g._edge(a, b, "corner", j.id)

        # degree-2 continuations: weld coincident road ends (same side) within 6 m
        ends_list = [(k, g.nodes[n]) for k, n in end_nodes.items()]
        for i in range(len(ends_list)):
            for jx in range(i + 1, len(ends_list)):
                (ra, sa, _), pa = ends_list[i]
                (rb, sb, _), pb = ends_list[jx]
                if ra != rb and geo.dist(pa, pb) < 6.0:
                    g._edge(end_nodes[ends_list[i][0]], end_nodes[ends_list[jx][0]], "weld")

        for pth in m.paths:
            chain = []
            for k, p in enumerate(geo.resample(pth.pts, STEP)):
                chain.append(g._node(f"{pth.id}:{k}", p))
            for a, b in zip(chain[:-1], chain[1:]):
                g._edge(a, b, "path", pth.id)
            for end in (chain[0], chain[-1]):
                near = [(geo.dist(g.nodes[end], p), n) for n, p in g.nodes.items() if not n.startswith(pth.id)]
                if near:
                    d, n = min(near)
                    if d < 15.0:
                        g._edge(end, n, "walk")
        return g

    # ---------------------------------------------------------------- query
    def nearest(self, p: Pt) -> str:
        return min(self.nodes, key=lambda n: geo.dist(self.nodes[n], p))

    def route(self, a: Pt, b: Pt, avoid_crossings: Optional[set[str]] = None) -> Optional[dict]:
        """A* over the pedestrian graph. Returns waypoints/length/crossings or None when unreachable."""
        if not self.nodes:
            return None
        s, t = self.nearest(a), self.nearest(b)
        avoid = avoid_crossings or set()
        dist = {s: 0.0}
        prev: dict[str, tuple[str, str, Optional[str]]] = {}
        pq = [(geo.dist(self.nodes[s], self.nodes[t]), 0.0, s)]
        done = set()
        while pq:
            _, d, n = heapq.heappop(pq)
            if n in done:
                continue
            done.add(n)
            if n == t:
                break
            for (mn, w, kind, ref) in self.adj[n]:
                if kind == "crossing" and ref in avoid:
                    continue
                nd = d + w + (CROSSING_PENALTY if kind == "crossing" else 0.0)
                if nd < dist.get(mn, 1e18):
                    dist[mn] = nd
                    prev[mn] = (n, kind, ref)
                    heapq.heappush(pq, (nd + geo.dist(self.nodes[mn], self.nodes[t]), nd, mn))
        if t not in dist:
            return None
        chain, n = [t], t
        crossings: list[str] = []
        while n != s:
            pn, kind, ref = prev[n]
            if kind == "crossing" and ref:
                crossings.append(ref)
            chain.append(pn)
            n = pn
        chain.reverse()
        crossings.reverse()
        way = [a] + [self.nodes[n] for n in chain] + [b]
        return {"waypoints": way, "length": geo.polyline_length(way), "crossings": crossings}

    # ---------------------------------------------------------------- io
    def to_dict(self) -> dict:
        keys = list(self.nodes)
        idx = {k: i for i, k in enumerate(keys)}
        edges = []
        seen = set()
        for a, lst in self.adj.items():
            for (b, w, kind, ref) in lst:
                key = (min(idx[a], idx[b]), max(idx[a], idx[b]), kind)
                if key in seen:
                    continue
                seen.add(key)
                edges.append([idx[a], idx[b], kind, ref])
        return {"nodes": [[round(self.nodes[k][0], 3), round(self.nodes[k][1], 3)] for k in keys],
                "edges": edges}
