"""Nominal walker: a synthetic reference trajectory used ONLY to check that a specification is satisfiable.

It is a validation device, like the route planner: it never runs in the player (the human is always the ego
pedestrian). The walker follows the pedestrian route through the goal zones in formula order, waits where the
formula asks it to wait (hold windows, "until the signal is green", gated crossings) and, if the formula contains
``look_at`` atoms, keeps its gaze on their target (an idealised attentive participant). The goal and safety formulas are
then evaluated on the resulting trace with the SAME monitor the player uses, which gives a nominal robustness margin.
"""
from __future__ import annotations

import math
from typing import Optional

from .. import geo
from . import formula as F
from .monitor import Monitor, Sample, dist_to_obb

DT = 0.1
WALK = 1.3                    # m/s
VEHICLE_BOX = (4.6, 2.0, 1.4)   # length, width, centre offset ahead of the reference point (rear axle)
WALKER_BOX = (0.6, 0.6, 0.0)
MAX_WAIT = 150.0


# ------------------------------------------------------------------ the world over time
def signal_state(cycle: dict, t: float) -> str:
    state = cycle["initial"]
    nxt = cycle["offset"] + (cycle["red"] if state == "red" else cycle["green"])
    while t >= nxt and nxt < 1e5:
        state = "green" if state == "red" else "red"
        nxt += cycle["green"] if state == "green" else cycle["red"]
    return state


class _Mover:
    def __init__(self, e: dict, t0: float):
        self.e, self.t0 = e, t0
        pts = [(e["start"]["x"], e["start"]["y"])] + [(r["x"], r["y"]) for r in e["route"]]
        self.pts = pts
        self.cum = [0.0]
        for a, b in zip(pts[:-1], pts[1:]):
            self.cum.append(self.cum[-1] + geo.dist(a, b) / max(e["speed"], 0.1))
        box = VEHICLE_BOX if e["role"] == "vehicle" else WALKER_BOX
        self.l, self.w, self.off = box

    def at(self, t: float) -> tuple:
        e = self.e
        h = e["start"]["h"]
        if not e["moving"] or t <= self.t0:
            x, y = self.pts[0]
        else:
            u = t - self.t0
            if u >= self.cum[-1]:
                x, y = self.pts[-1]
                if len(self.pts) > 1:
                    h = geo.heading(self.pts[-2], self.pts[-1])
            else:
                i = max(j for j in range(len(self.cum)) if self.cum[j] <= u)
                i = min(i, len(self.pts) - 2)
                seg = max(self.cum[i + 1] - self.cum[i], 1e-9)
                f = (u - self.cum[i]) / seg
                a, b = self.pts[i], self.pts[i + 1]
                x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                h = geo.heading(a, b)
        c, s = math.cos(h), math.sin(h)
        return (x + c * self.off, y + s * self.off, h, self.l, self.w)


def _plan(goal: dict) -> tuple[list[dict], list[tuple]]:
    """(stages, look_targets): stages = ordered zone visits with optional dwell/wait; look_targets = [('entity'|'point', ...)]."""
    stages: list[dict] = []
    looks: list[tuple] = []

    def zone_center(z):
        if z["kind"] == "disc":
            return (z["x"], z["y"])
        if z["kind"] == "rect":
            return (z["cx"], z["cy"])
        return None

    def visit(n):
        op = n["op"]
        if op == "in_zone":
            c = zone_center(n["zone"])
            if c:
                stages.append({"c": c, "dwell": 0.0, "wait": None})
        elif op in ("eventually",):
            visit(n["arg"])
        elif op == "always":
            a = n["arg"]
            if a["op"] == "in_zone":
                c = zone_center(a["zone"])
                if c and n.get("end") is not None:
                    stages.append({"c": c, "dwell": float(n["end"]) - float(n.get("start", 0)), "wait": None})
                    return
            visit(a)
        elif op == "until":
            l, r = n["left"], n["right"]
            if l["op"] == "in_zone" and r["op"] == "signal_is":
                c = zone_center(l["zone"])
                if c:
                    stages.append({"c": c, "dwell": 0.0, "wait": (r["signal"], r["state"])})
                    return
            visit(l)
            visit(r)
        elif op in ("and", "or"):
            for c in n["args"]:
                visit(c)
        elif op == "look_at":
            looks.append(("entity", n["entity"]) if "entity" in n else ("point", tuple(n["point"])))
        elif op in ("not", "prev"):
            visit(n["arg"])
        elif op == "implies":
            visit(n["a"]); visit(n["b"])

    visit(goal)
    return stages, looks


def _gates(safety: list[dict]) -> list[tuple]:
    """Crossings the walker must not enter on red: [(rect zone, signal)] from obey_signal-shaped safety formulas."""
    out = []
    for f in safety:
        for n in F.walk(f):
            if n["op"] == "implies" and n["b"]["op"] == "signal_is":
                zs = [z for z in F.zones_in(n["a"]) if z["kind"] == "rect"]
                if zs:
                    out.append((zs[0], n["b"]["signal"]))
    return out


def _keep_clear(safety: list[dict], movers: dict) -> list[tuple]:
    """[(entity, d)] the walker yields to: dist_ge atoms on entities that move."""
    out = []
    for f in safety:
        for n in F.atoms_in(f):
            if n["op"] == "dist_ge" and n["entity"] in movers and movers[n["entity"]].e["moving"]:
                out.append((n["entity"], float(n["d"])))
    return out


def _in_rect(p, z) -> bool:
    lx, ly = (p[0] - z["cx"]) * math.cos(z["h"]) + (p[1] - z["cy"]) * math.sin(z["h"]), \
             -(p[0] - z["cx"]) * math.sin(z["h"]) + (p[1] - z["cy"]) * math.cos(z["h"])
    return abs(lx) <= z["hl"] and abs(ly) <= z["hw"]


def _legs(model, a, b) -> list[tuple]:
    r = model.ped_graph.route(a, b)
    return [tuple(p) for p in r["waypoints"]] if r else [a, b]


def nominal(spec: dict, model, task: dict, t_abs: float, movers: dict) -> dict:
    """Walk the nominal participant through one task and evaluate its formulas. Returns margins and the duration."""
    goal, safety = task["goal"], task["safety"]
    user = next(e for e in spec["entities"] if e["role"] == "user")
    cycles = {c["signal"]: c for c in spec["signals"]}
    stages, looks = _plan(goal)
    gates = _gates(safety)
    yields = _keep_clear(safety, movers)
    p = (user["start"]["x"], user["start"]["y"])
    if task.get("origin") is not None:
        p = tuple(task["origin"])
    h = user["start"]["h"]
    samples: list[Sample] = []
    names = [e["name"] for e in spec["entities"] if e["role"] != "user"]
    horizon = float(task["timeout"]["baseline"])

    def look_target(t):
        if not looks:
            return None
        kind, v = looks[0]
        if kind == "point":
            return v
        m = movers.get(v)
        if m:
            q = m.at(t_abs + t)
            return (q[0], q[1])
        return None

    def snap(t, x, y, gaze, speed):
        ents = {}
        for n in names:
            if n in movers:
                ents[n] = movers[n].at(t_abs + t)
        sigs = {s: signal_state(c, t_abs + t) for s, c in cycles.items()}
        started = frozenset(n for n in F.events_in(goal) | {e for f in safety for e in F.events_in(f)} if n.startswith("move_")
                            and n[5:] in movers and t_abs + t >= movers[n[5:]].t0)
        samples.append(Sample(x, y, gaze, speed, model.surface_at((x, y)), ents, sigs, started))

    t = 0.0
    snap(0.0, p[0], p[1], h, 0.0)
    final_hold = max([float(n["end"]) for n in F.walk(goal) if n["op"] in ("eventually", "always", "until") and n.get("end") is not None]
                     + [0.0])
    for st in stages:
        for q in _legs(model, p, st["c"])[1:]:
            while geo.dist(p, q) > 1e-6 and t < horizon:
                step = min(WALK * DT, geo.dist(p, q))
                hd = geo.heading(p, q)
                nx, ny = p[0] + math.cos(hd) * step, p[1] + math.sin(hd) * step
                blocked = next((s for z, s in gates if not _in_rect(p, z) and _in_rect((nx, ny), z)
                                and s in cycles and signal_state(cycles[s], t_abs + t) != "green"), None)
                def too_close(pt, tt):
                    for en, d in yields:
                        for ahead in (0.0, 1.0, 2.0):
                            e = movers[en].at(t_abs + tt + ahead)
                            if dist_to_obb(pt, (e[0], e[1]), e[2], e[3], e[4]) < d + 0.8:
                                return True
                    return False

                if yields and too_close((nx, ny), t):                  # a polite pedestrian yields to approaching traffic
                    waited = 0.0
                    while too_close((nx, ny), t) and waited < 60.0 and t < horizon:
                        t += DT; waited += DT
                        lt = look_target(t)
                        snap(t, p[0], p[1], geo.heading(p, lt) if lt else hd, 0.0)
                    continue
                if blocked:
                    waited = 0.0
                    while signal_state(cycles[blocked], t_abs + t) != "green" and waited < MAX_WAIT and t < horizon:
                        t += DT; waited += DT
                        lt = look_target(t)
                        snap(t, p[0], p[1], geo.heading(p, lt) if lt else hd, 0.0)
                    continue
                p = (nx, ny)
                t += DT
                lt = look_target(t)
                snap(t, p[0], p[1], geo.heading(p, lt) if lt else hd, step / DT)
        waited = 0.0
        cond = st["wait"]
        while t < horizon and waited < MAX_WAIT and ((waited < st["dwell"]) or
                                                     (cond and cond[0] in cycles and signal_state(cycles[cond[0]], t_abs + t) != cond[1])):
            t += DT; waited += DT
            lt = look_target(t)
            snap(t, p[0], p[1], geo.heading(p, lt) if lt else h, 0.0)
    end = min(horizon, t + max(final_hold - t, 1.0)) if final_hold > t else t + 1.0
    while t < min(end, horizon):
        t += DT
        lt = look_target(t)
        snap(t, p[0], p[1], geo.heading(p, lt) if lt else h, 0.0)
    mon = Monitor(samples, DT, complete=True)
    g = mon.rho(goal, 0)[0]
    sf = [mon.rho(f, 0)[0] for f in safety]
    return {"goal": round(g, 3), "safety": [round(x, 3) for x in sf],
            "min_safety": round(min(sf), 3) if sf else None, "duration": round(t, 1),
            "ok": g >= 0 and all(x >= 0 for x in sf), "end": p}


def build_movers(spec: dict, user_xy_by_time=None, starts: Optional[dict] = None) -> dict:
    """One _Mover per non-user entity. ``starts`` maps task id -> (start, end) absolute times for task-triggered NPCs."""
    starts = starts or {}
    movers = {}
    user = next(e for e in spec["entities"] if e["role"] == "user")
    for e in spec["entities"]:
        if e["role"] == "user":
            continue
        w = e["start_when"]
        t0 = 0.0
        if w["kind"] == "time":
            t0 = float(w["value"])
        elif w["kind"] in ("task_started", "task_done") and w.get("task") in starts:
            s0, s1 = starts[w["task"]]
            t0 = s0 if w["kind"] == "task_started" else s1
        elif w["kind"] == "user_within":
            d = float(w["value"])
            u0 = (user["start"]["x"], user["start"]["y"])
            tgt = next((tk["target"] for tk in spec["tasks"] if tk["target"]), None)
            if tgt:
                length = geo.dist(u0, (tgt["x"], tgt["y"]))
                for k in range(0, int(length / (WALK * DT)) + 1):
                    f = min(1.0, k * WALK * DT / max(length, 1e-6))
                    q = (u0[0] + (tgt["x"] - u0[0]) * f, u0[1] + (tgt["y"] - u0[1]) * f)
                    if geo.dist(q, (e["start"]["x"], e["start"]["y"])) < d:
                        t0 = k * DT
                        break
        movers[e["name"]] = _Mover(e, t0)
    return movers


def margins(spec: dict, model) -> dict[int, dict]:
    """Nominal margins per task id, tasks processed in order so dependent timings chain."""
    out: dict[int, dict] = {}
    times: dict[int, tuple] = {}
    origin: dict[int, tuple] = {}
    for t in sorted(spec["tasks"], key=lambda t: t["id"]):
        if "goal" not in t:
            continue
        start = float(t["start_time"])
        for d in t["depends_on"]:
            start = max(start, times.get(d, (0.0, 0.0))[1])
        movers = build_movers(spec, starts=times)
        tk = dict(t)
        if t["depends_on"]:
            tk["origin"] = origin.get(max(t["depends_on"]))
        r = nominal(spec, model, tk, start, movers)
        times[t["id"]] = (start, start + r["duration"])
        origin[t["id"]] = r["end"]
        r.pop("end")
        out[t["id"]] = r
    return out
