"""Top-down rendering with matplotlib: the map and a static scenario overlay (start, targets, vehicle routes)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.figure import Figure                               # noqa: E402
from matplotlib.patches import Circle, Polygon                     # noqa: E402

from . import geo                                                  # noqa: E402
from .mapmodel import MapModel                                     # noqa: E402

BG, GROUND = "#141b22", "#1c2630"
C = {"building": "#3d4854", "road": "#2a2f36", "sidewalk": "#5a626c", "green": "#27442d", "water": "#2b5d86",
     "path": "#8a7a58", "rail": "#6a5e55", "zebra": "#f2f2f2", "signals": "#ffb14a", "uncontrolled": "#9aa5ad",
     "user": "#3ddc84", "vehicle": "#ff6b6b", "walker": "#ffd166", "target": "#35e0ff"}


def _band(pts, d0: float, d1: float):
    a, b = geo.offset_polyline(pts, d0), geo.offset_polyline(pts, d1)
    return a + b[::-1]


def draw_map(ax, m: MapModel) -> None:
    """Static city on an axes (metres, y up)."""
    ax.set_facecolor(GROUND)
    for a in m.areas:
        ax.add_patch(Polygon(a.pts, closed=True, fc=C["water" if a.atype == "water" else "green"], ec="none", zorder=1))
    for r in m.roads:
        tr = geo.sub_polyline(r.pts, r.trim_start, r.length - r.trim_end)
        if len(tr) < 2:
            continue
        if r.sidewalk_left > 0:
            ax.add_patch(Polygon(_band(tr, r.width / 2, r.width / 2 + r.sidewalk_left), fc=C["sidewalk"], ec="none", zorder=2))
        if r.sidewalk_right > 0:
            ax.add_patch(Polygon(_band(tr, -r.width / 2, -r.width / 2 - r.sidewalk_right), fc=C["sidewalk"], ec="none", zorder=2))
    for j in m.junctions:
        for c in j.corners:
            ax.add_patch(Polygon(c, fc=C["sidewalk"], ec="none", zorder=2))
    for r in m.roads:
        tr = geo.sub_polyline(r.pts, r.trim_start, r.length - r.trim_end)
        if len(tr) >= 2:
            ax.add_patch(Polygon(_band(tr, r.width / 2, -r.width / 2), fc=C["road"], ec="none", zorder=3))
            if not r.oneway:
                xs, ys = zip(*tr)
                ax.plot(xs, ys, color="#c9a227", lw=0.6, ls=(0, (6, 10)), zorder=4)
    for j in m.junctions:
        if len(j.polygon) >= 3:
            ax.add_patch(Polygon(j.polygon, fc=C["road"], ec="none", zorder=3))
    for p in m.paths:
        ax.add_patch(Polygon(_band(p.pts, p.width / 2, -p.width / 2), fc=C["path"], ec="none", zorder=3))
    for r in m.railways:
        xs, ys = zip(*r.pts)
        ax.plot(xs, ys, color=C["rail"], lw=2, ls=(0, (4, 2)), zorder=3)
    for b in m.barriers:
        xs, ys = zip(*b.pts)
        ax.plot(xs, ys, color="#8b7d66", lw=1, zorder=4)
    for b in m.buildings:
        ax.add_patch(Polygon(b.pts, fc=C["building"], ec="#2b343d", lw=0.5, zorder=5))
    for c in m.crossings:
        dx, dy = math.cos(c.heading), math.sin(c.heading)
        a, b = c.endpoints()
        ax.plot([a[0], b[0]], [a[1], b[1]], color=C.get(c.control, "#fff"), lw=max(2.0, c.width * 0.9), solid_capstyle="butt",
                alpha=0.9, zorder=4)
        _ = dx, dy
    for p in m.props:
        col = "#4aa3ff" if p.ptype == "bus_stop" else "#6f7d89" if p.ptype != "tree" else "#2f6b3a"
        ax.add_patch(Circle(p.pos, 2.2 if p.ptype == "bus_stop" else 0.9 if p.ptype != "tree" else 1.6, fc=col, ec="none", zorder=6))
    x0, y0, x1, y1 = m.bounds
    pad = 15
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def _overlay(ax, spec: dict) -> None:
    for e in spec["entities"]:
        if e["route"]:
            pts = [(e["start"]["x"], e["start"]["y"])] + [(p["x"], p["y"]) for p in e["route"]]
            xs, ys = zip(*pts)
            ax.plot(xs, ys, color=C["vehicle"], lw=1.6, alpha=0.8, ls="--", zorder=7)
    for t in spec["tasks"]:
        for fm in list(t.get("safety", [])) + [t["goal"]] if t.get("goal") else []:
            stack = [fm]
            while stack:                                   # draw every near_path corridor found in the task's formulas
                n = stack.pop()
                if n["op"] == "near_path":
                    xs, ys = zip(*[tuple(q) for q in n["path"]])
                    ax.plot(xs, ys, color=C["target"], lw=2, alpha=0.9, zorder=7)
                stack += [n[k] for k in ("arg", "a", "b", "left", "right") if k in n] + (n["args"] if n["op"] in ("and", "or") else [])
    for e in spec["entities"]:
        col = C["user"] if e["role"] == "user" else C["vehicle"] if e["role"] == "vehicle" else C["walker"]
        ax.add_patch(Circle((e["start"]["x"], e["start"]["y"]), 2.4 if e["role"] == "user" else 1.6, fc=col, ec="white", lw=0.8, zorder=8))
    for t in spec["tasks"]:
        if t["target"]:
            tx, ty = t["target"]["x"], t["target"]["y"]
            ax.add_patch(Circle((tx, ty), max(2.5, t["tolerance"]), fc="none", ec=C["target"], lw=2, zorder=8))
            ax.text(tx, ty, str(t["id"]), color=C["target"], fontsize=9, ha="center", va="center", weight="bold", zorder=9)


def map_figure(m: MapModel, spec: Optional[dict] = None, size: tuple[float, float] = (7.2, 5.6)) -> Figure:
    fig, ax = plt.subplots(figsize=size, dpi=100)
    fig.patch.set_facecolor(BG)
    draw_map(ax, m)
    if spec:
        _overlay(ax, spec)
        ax.set_title(f"{spec['name']}  ({spec.get('scenario_type') or 'scenario'})", color="#e6edf3", fontsize=10)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95 if spec else 0.99, bottom=0.01)
    return fig


def map_image_png(m: MapModel, px: int = 768) -> bytes:
    """Annotated top-down PNG for a vision-language model: north up, metric grid with coordinates, crossing / bus-stop / road ids."""
    import io

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(px / 100, px / 100), dpi=100)
    FigureCanvasAgg(fig)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.07, 0.05, 0.92, 0.93])
    draw_map(ax, m)
    x0, y0, x1, y1 = m.bounds
    step = 50.0 if max(x1 - x0, y1 - y0) > 200 else 25.0
    xs = [step * k for k in range(int((x0 - 15) // step), int((x1 + 15) // step) + 2)]
    ys = [step * k for k in range(int((y0 - 15) // step), int((y1 + 15) // step) + 2)]
    for x in xs:
        ax.axvline(x, color="#ffffff", lw=0.3, alpha=0.18, zorder=1)
    for y in ys:
        ax.axhline(y, color="#ffffff", lw=0.3, alpha=0.18, zorder=1)
    ax.set_xticks([x for x in xs if x0 - 15 <= x <= x1 + 15])
    ax.set_yticks([y for y in ys if y0 - 15 <= y <= y1 + 15])
    ax.tick_params(colors="#c8d1d9", labelsize=7, length=2)
    ax.set_xlabel("x (m, east)", color="#c8d1d9", fontsize=7)
    ax.set_ylabel("y (m, north)", color="#c8d1d9", fontsize=7)
    for r in m.roads:
        i = len(r.pts) // 2
        ax.text(r.pts[i][0], r.pts[i][1], r.id, color="#e6edf3", fontsize=6, ha="center", va="center", zorder=9,
                bbox=dict(boxstyle="round,pad=0.15", fc="#000000", ec="none", alpha=0.45))
    for c in m.crossings:
        ax.text(c.pos[0], c.pos[1], c.id.replace("crossing_", "c"), color="#ffd166", fontsize=7, ha="center", va="center", zorder=10, weight="bold")
    for p in m.props:
        if p.ptype == "bus_stop":
            ax.text(p.pos[0], p.pos[1] + 4, p.id.replace("bus_stop_", "bus"), color="#4aa3ff", fontsize=7, ha="center", zorder=10, weight="bold")
    ax.text(0.01, 0.99, "N ↑   crossings c<n> (yellow = marked), bus<n> = bus stops, road_<n> = roads", transform=ax.transAxes,
            color="#e6edf3", fontsize=6.5, va="top", zorder=11)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=BG)
    return buf.getvalue()
