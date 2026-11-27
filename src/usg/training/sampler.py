"""Procedural training examples: (map, request, level) -> target reply. Every example is verified by the gates before it is kept.

The request wording below is written for training and is deliberately not copied from ``eval/prompts_*.json`` (``near_eval`` rejects close matches).
Targets use only ids that appear in the one-shot context of the same request.
"""
from __future__ import annotations

import difflib
import json
import random
import re
from pathlib import Path
from typing import Optional

from .. import grounding
from ..tools import ToolServer
from .oneshot import crossing_table, format_reply

NOUN = {"bus_stop": "bus stop", "bench": "bench", "waste_basket": "waste basket", "tree": "tree", "street_lamp": "street lamp", "bollard": "bollard"}
SYN = {"bus_stop": ["bus stop", "bus-stop"], "bench": ["bench", "public bench"], "waste_basket": ["waste basket", "litter bin", "trash can", "rubbish bin"],
       "tree": ["tree", "street tree"], "street_lamp": ["street lamp", "lamp post", "street light"], "bollard": ["bollard"]}
PREFIX = ["", "", "", "Create a task where the user has to do this: ", "For the participant: ", "I want a scenario in which the walker must do the following. ",
          "Design an exercise: ", "Please set this up. ", "Task: ", "Make the person "]
VEH = [("car", "car_white"), ("car", "car_red"), ("car", "car_blue"), ("van", "van_red"), ("bus", "bus_blue"), ("truck", "truck_yellow")]
KINDS = ["ptp_env", "ptp_road", "cpath", "env_con", "dyn_nav", "dep_comp", "indep_comp", "signal", "signal_car", "look_cross"]
LEVELS_OF = {k: (0, 1, 2) for k in KINDS}
LEVELS_OF["look_cross"] = (1, 2)                       # the script helpers of level 0 cannot express a gaze goal


def call(name: str, **args) -> dict:
    return {"op": "call", "name": name, "args": args}


def side(c: str, s: str, r: float = 2) -> dict:
    return {"kind": "crossing_side", "id": c, "side": s, "r": r}


def feat(i: str) -> dict:
    return {"kind": "feature", "id": i, "r": 3}


def task(name: str, text: str, goal: dict, t: tuple[int, int], safety: Optional[list] = None, **extra) -> dict:
    d = {"name": name, "instruction": text, "goal": goal}
    if safety:
        d["safety"] = safety
    d["timeout"] = {"initial": t[0], "baseline": t[1]}
    d.update(extra)
    return d


def near_eval(text: str, eval_texts: list[str], limit: float = 0.82) -> bool:
    return any(difflib.SequenceMatcher(None, text.lower(), e.lower()).ratio() >= limit for e in eval_texts)


def _head(kind: str, name: str) -> str:
    return f'from usg.dsl import *\nscenario = ScenarioBuilder("{name}", MAP, scenario_type="{kind}")\n'


WORLD_EMPTY = _head("custom", "scenario") + "handles = scenario.apply_spec(SPEC)"


def _landmark(t: ToolServer, rng: random.Random, kinds: list[str], exclude: tuple = ()) -> Optional[tuple[str, dict]]:
    """A prop of one of ``kinds`` that the context lists (the three nearest of its type) and that stands on walkable ground beside a road."""
    order = kinds[:]
    rng.shuffle(order)
    for k in order:
        if k in exclude:
            continue
        inst = grounding.OBJECTS[k][2](t.q)
        ids = [i["id"] for i in sorted(inst, key=lambda i: i["pos"][0] ** 2 + i["pos"][1] ** 2)[:3]]    # the ids the context lists
        full = {p["id"]: p for p in t.q.props(k)}                                                          # these records carry the road
        near = [full[i] for i in ids if i in full]
        rng.shuffle(near)
        for p in near:
            if p.get("road") and t.model.surface_at(tuple(p["pos"])) in ("sidewalk", "path", "ground"):
                return k, p
    return None


def _car(road: str, s: float, speed: float, model: str, handle: str = "handles[0]", back: float = 30.0) -> str:
    return (f'length = MAP.road("{road}")["length"]\n'
            f'route = MAP.drive_route("{road}", max(0.0, {s} - {back}), min(length, {s} + 30.0), "forward")\n'
            f'scenario.vehicle("Car1", route[0], route[1:], speed={speed}, model="{model}", start_when=when_task_starts({handle}))')


def _wrap_def(rng: random.Random, goal: dict, safety: list) -> tuple[dict, dict, list]:
    """Level 2: move the goal (or the safety rules) into an own definition."""
    if safety and rng.random() < 0.5:
        body = safety[0] if len(safety) == 1 else {"op": "and", "args": safety}
        name = rng.choice(["stay_safe", "safety_rule", "keep_safe"])
        return {name: {"params": [], "body": body}}, goal, [call(name)]
    if goal.get("name") in ("cross", "reach"):
        key = "far_zone" if goal["name"] == "cross" else "zone"
        name = {"cross": rng.choice(["get_across", "cross_over"]), "reach": rng.choice(["go_there", "arrive"])}[goal["name"]]
        return {name: {"params": ["z"], "body": call(goal["name"], **{key: {"param": "z"}})}}, call(name, z=goal["args"][key]), safety
    name = rng.choice(["whole_job", "journey"])
    return {name: {"params": [], "body": goal}}, call(name), safety


def sample(t: ToolServer, kind: str, level: int, rng: random.Random) -> Optional[tuple[str, str, dict]]:
    """(request, target reply, meta) or None if this map cannot host the kind."""
    table = crossing_table(t)
    sig = [c for c in table if c["control"] == "signals"]
    zebra = [c for c in table if c["control"] == "zebra"]
    timeout = rng.choice([(60, 90), (60, 100), (75, 110), (90, 130)])
    green, red = rng.choice([(12, 18), (15, 20), (10, 25), (20, 15), (15, 15)])
    speed = rng.choice([5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    veh, vmodel = rng.choice(VEH)
    spec: Optional[dict] = None
    code0 = world = ""
    cr = None
    if table:
        wants_zebra = bool(zebra) and rng.random() < 0.4
        cr = rng.choice(zebra if wants_zebra else table)
        if kind in ("env_con", "dyn_nav"):                     # no light rule in these tasks: use a crossing without signals
            plain = [c for c in table if c["control"] != "signals"]
            cr = rng.choice([c for c in plain if c["control"] == "zebra"] if wants_zebra else plain) if plain else None
    zeb = "zebra crossing" if cr and cr["control"] == "zebra" else rng.choice(["crossing", "pedestrian crossing", "crosswalk"])

    if kind == "ptp_env":
        got = _landmark(t, rng, list(NOUN))
        if not got:
            return None
        k, p = got
        n = rng.choice(SYN[k])
        req = rng.choice([f"Walk over to a {n}.", f"Head to the {n} using the pavement.", f"Get to a {n} on foot without going on the street.",
                          f"Find a {n} and go there.", f"The goal is to arrive at a {n}.", f"Lead the participant to the closest {n}."])
        text = f"Walk to the {NOUN[k]}."
        spec = {"tasks": [task("to_landmark", text, call("reach", zone=feat(p["id"])), timeout)]}
        code0 = (_head("ptp_env", "ptp_env") + f'dest = MAP.place("{p["id"]}")\nroad = "{p["road"]}"\n'
                 f'start = MAP.sidewalk_at(road, MAP.side_of_road(dest), max(6.0, MAP.road_s_of(dest) - {rng.choice([25, 30, 40])}.0))\n'
                 f'scenario.user(start.facing(dest))\nscenario.go_to(dest, "{text}", name="to_landmark", tolerance=2.0, timeout=MAP.walk_time(start, dest))')
    elif kind == "ptp_road":
        if not cr:
            return None
        ds = rng.choice([5.0, 6.0, 7.0])
        req = rng.choice(["Step onto the road and wait at the point beyond the crossing.", "The participant has to reach a point on the carriageway.",
                          "Send the walker out onto the road to a marked point.", "Make the user go and stand on the road near a crosswalk.",
                          "Reach the target in the middle of the street."])
        place = t.q.along_road(cr["road"], cr["road_s"] + ds, 0.0)
        if t.model.surface_at((place.x, place.y)) != "road":
            return None
        text = "Go to the marked point on the road."
        spec = {"tasks": [task("to_road_point", text, call("reach", zone={"kind": "disc", "x": round(place.x, 1), "y": round(place.y, 1), "r": 2}), timeout)]}
        code0 = (_head("ptp_road", "ptp_road") + f'start = MAP.crossing_side("{cr["id"]}", "start", inset=2.0)\n'
                 f'dest = MAP.along_road("{cr["road"]}", {cr["road_s"]} + {ds})\nscenario.user(start)\n'
                 f'scenario.go_to(dest, "{text}", name="to_road_point", tolerance=1.5, timeout={timeout[1]})')
    elif kind == "cpath":
        if not cr:
            return None
        tol = rng.choice([1.8, 2.0, 2.5])
        req = rng.choice([f"Get across at the {zeb} while keeping to the marked path.", f"Use the corridor over the {zeb} and do not leave it.",
                          f"The user must cross inside a narrow marked lane at a {zeb}.", f"Follow the route across the {zeb} without straying from it.",
                          f"Cross while staying on the path drawn over the {zeb}."])
        text = "Cross and stay inside the corridor."
        path = [cr["start_side"], cr["end_side"]]
        spec = {"tasks": [task("cross_corridor", text, call("cross", far_zone=side(cr["id"], "end")), timeout,
                               [call("stay_near_path", path=path, tol=tol)])]}
        code0 = (_head("cpath", "cpath") + f'a = MAP.crossing_side("{cr["id"]}", "start", inset=2.0)\nmid = MAP.place("{cr["id"]}", 0.5, 0.0)\n'
                 f'b = MAP.crossing_side("{cr["id"]}", "end", inset=2.0)\nscenario.user(a)\n'
                 f'scenario.follow_path([a, mid, b], "{text}", name="cross_corridor", corridor={tol}, timeout={timeout[1]})')
    elif kind == "env_con":
        if not cr:
            return None
        centre = t.q.place(cr["id"])
        free = len([p for p in t.q.kerb_slots(cr["road"], "right", 7.0) if p.dist(centre) > 8.0])
        if free < 2:
            return None
        n = min(free, rng.choice([2, 3, 4]))
        req = rng.choice([f"Cross at a {zeb} next to a line of parked cars and do not bump into them.", f"Put some parked vehicles near the {zeb}; the user crosses without hitting any.",
                          f"Get across the street while parked cars stand along the kerb; avoid contact.", f"Several parked cars block the view at the {zeb}. Cross without touching them."])
        names = [f"Car{i + 1}" for i in range(n)]
        text = "Cross without touching the parked cars."
        spec = {"tasks": [task("cross_past_parked", text, call("cross", far_zone=side(cr["id"], "end")), timeout,
                               [call("collision_free", entity=x, r=0.3) for x in names])]}
        parked = (f'centre = MAP.place("{cr["id"]}")\nslots = sorted([p for p in MAP.kerb_slots("{cr["road"]}", "right", 7.0) if p.dist(centre) > 8.0], key=lambda p: p.dist(centre))[:{n}]\n'
                  'cars = [scenario.parked_vehicle("Car" + str(i + 1), p, VEHICLE_MODELS[i % 4]) for i, p in enumerate(slots)]')
        world = (_head("custom", "scenario") + f'scenario.user(MAP.crossing_side("{cr["id"]}", "start", inset=1.5))\n' + parked + "\nhandles = scenario.apply_spec(SPEC)")
        code0 = (_head("env_con", "env_con") + f'scenario.user(MAP.crossing_side("{cr["id"]}", "start", inset=1.5))\n' + parked +
                 f'\nscenario.cross("{cr["id"]}", "start", "{text}", name="cross_past_parked", avoid=cars, timeout={timeout[1]})')
    elif kind == "dyn_nav":
        if not cr:
            return None
        req = rng.choice([f"A {veh} comes along while the user crosses at a {zeb}; they must not be hit.", f"Cross the street at a {zeb} as a {veh} is driving toward it.",
                          f"Have an approaching {veh} at the {zeb} and require the walker to stay clear.", f"Get over the road safely although a {veh} drives past.",
                          f"The participant crosses while a moving {veh} approaches. Collision means failure."])
        text = f"Cross and keep clear of the {veh}."
        spec = {"tasks": [task("cross_with_traffic", text, call("cross", far_zone=side(cr["id"], "end")), timeout,
                               [call("collision_free", entity="Car1", r=0.3)])]}
        world = (_head("custom", "scenario") + f'scenario.user(MAP.crossing_side("{cr["id"]}", "start", inset=2.0))\nhandles = scenario.apply_spec(SPEC)\n'
                 + _car(cr["road"], cr["road_s"], speed, vmodel))
        code0 = (_head("dyn_nav", "dyn_nav") + f'scenario.user(MAP.crossing_side("{cr["id"]}", "start", inset=2.0))\n'
                 f'task = scenario.cross("{cr["id"]}", "start", "{text}", name="cross_with_traffic", avoid=["Car1"], timeout={timeout[1]})\n'
                 + _car(cr["road"], cr["road_s"], speed, vmodel, "task"))
    elif kind in ("dep_comp", "indep_comp"):
        first = _landmark(t, rng, list(NOUN))
        second = first and _landmark(t, rng, list(NOUN), (first[0],))
        if not second:
            return None
        picks = [first, second]
        if kind == "dep_comp" and rng.random() < 0.35:
            third = _landmark(t, rng, list(NOUN), (first[0], second[0]))
            if third:
                picks.append(third)
        far = max(((a["pos"][0] - b["pos"][0]) ** 2 + (a["pos"][1] - b["pos"][1]) ** 2) ** 0.5 for _, a in picks for _, b in picks)
        if far > 140.0:                                          # walking routes much longer than this exceed ordinary time limits
            return None
        words = [rng.choice(SYN[k]) for k, _ in picks]
        listing = " and ".join(f"a {w}" for w in words) if len(words) == 2 else f"a {words[0]}, a {words[1]} and a {words[2]}"
        if kind == "dep_comp":
            seq = ", then ".join(f"a {w}" for w in words)
            req = rng.choice([f"Visit {seq}. The order matters.", f"Go to {seq}, in exactly this order.", f"Start by walking to {seq} afterwards.",
                              f"One after the other: {seq}."])
        else:
            req = rng.choice([f"Collect two or more stops, {listing}; the user chooses the order.", f"Walk to {listing} in whichever order you like.",
                              f"Both targets count: {listing}. Order is free.", f"The participant should get to {listing}, no fixed sequence."])
        tasks, lines, hs = [], [], []
        for i, (k, p) in enumerate(picks):
            nm, text = f"to_{k}", f"Walk to the {NOUN[k]}."
            extra = {}
            if kind == "dep_comp" and i:
                extra["after"] = [f"to_{picks[i - 1][0]}"]
            if kind == "indep_comp":
                extra["mode"] = "parallel"
            tasks.append(task(nm, text, call("reach", zone=feat(p["id"])), (220 + 80 * i, 340 + 100 * i), **extra))
            lines.append(f't{i} = scenario.go_to(MAP.place("{p["id"]}"), "{text}", name="{nm}", tolerance=2.0, timeout={340 + 100 * i})')
            hs.append(f"t{i}")
        spec = {"tasks": tasks}
        p0 = picks[0][1]
        group = "sequence" if kind == "dep_comp" else "parallel"
        code0 = (_head(kind, kind) + f'dest = MAP.place("{p0["id"]}")\nstart = MAP.sidewalk_at("{p0["road"]}", MAP.side_of_road(dest), max(6.0, MAP.road_s_of(dest) - 25.0))\n'
                 f'scenario.user(start.facing(dest))\n' + "\n".join(lines) + f'\nscenario.{group}([{", ".join(hs)}], "{group}_group")')
    else:                                                        # signal, signal_car, look_cross
        if kind in ("signal", "signal_car"):
            if not sig:
                return None
            cr = rng.choice(sig)
            sg, cid = cr["signal"], cr["id"]
            goal = {"op": "then", "args": [call("wait_for_green", zone=side(cid, "start", 3), signal=sg), call("cross", far_zone=side(cid, "end"))]}
            safety = [call("obey_signal", zone={"kind": "crossing", "id": cid}, signal=sg)]
            cycle = f'scenario.signal_cycle("{cid}", green={green}, red={red}, initial="red")\n'
            wait = (60 + red + 20, 110 + red + green + 20)
            if kind == "signal":
                req = rng.choice(["At the traffic light, wait for green before you cross.", "Cross only once the pedestrian signal shows green.",
                                  "Stand at the signalised crossing until it is green and then walk over.", "Respect the pedestrian light: no crossing on red.",
                                  "The user waits for the green light and crosses afterwards."])
                text = "Wait for green, then cross."
                spec = {"tasks": [task("cross_on_green", text, goal, wait, safety)]}
            else:
                req = rng.choice([f"Cross on green at the traffic light while a {veh} is driving nearby; do not get hit.",
                                  f"There is a pedestrian signal and an approaching {veh}. Wait for green and stay clear of it.",
                                  f"Obey the pedestrian light and keep away from the moving {veh}.",
                                  f"Wait for the green light, then cross, with a {veh} passing on the street."])
                text = f"Cross on green; avoid the {veh}."
                spec = {"tasks": [task("cross_on_green", text, goal, wait, safety + [call("collision_free", entity="Car1", r=0.3)])]}
            world = (_head("custom", "scenario") + f'scenario.user(MAP.crossing_side("{cid}", "start", inset=2.0))\n' + cycle + "handles = scenario.apply_spec(SPEC)"
                     + ("\n" + _car(cr["road"], cr["road_s"], speed, vmodel) if kind == "signal_car" else ""))
            code0 = (_head("custom", kind) + f'scenario.user(MAP.crossing_side("{cid}", "start", inset=2.0))\n' + cycle +
                     f'task = scenario.cross("{cid}", "start", "{text}", name="cross_on_green", timeout={wait[1]}, obey_signal=True'
                     + (', avoid=["Car1"])\n' + _car(cr["road"], cr["road_s"], speed, vmodel, "task") if kind == "signal_car" else ")"))
        else:
            if not cr:
                return None
            angle = rng.choice([30, 35, 40, 45])
            req = rng.choice([f"Before crossing, the user should look at the {veh} that is coming, then walk over.", f"Look for the approaching {veh} first and cross afterwards without a collision.",
                              f"Check the oncoming {veh} with your eyes, then get across the road.", f"First look at the moving {veh}; only then cross at the {zeb}."])
            spec = {"tasks": [task("check_traffic", f"Look at the {veh}.", call("look", entity="Car1", angle=angle, seconds=12), (15, 25)),
                              task("cross_clear", "Cross and stay clear.", call("cross", far_zone=side(cr["id"], "end")), timeout,
                                   [call("collision_free", entity="Car1", r=0.3)], after=["check_traffic"])]}
            world = (_head("custom", "scenario") +
                     f'scenario.user(MAP.crossing_side("{cr["id"]}", "start", inset=2.0).facing(MAP.along_road("{cr["road"]}", {cr["road_s"]} + 20.0)))\n'
                     "handles = scenario.apply_spec(SPEC)\n" + _car(cr["road"], cr["road_s"], speed, vmodel))

    req = rng.choice(PREFIX) + req
    if req.startswith("Make the person "):
        req = "Make the person do this. " + req[len("Make the person "):]
    if level == 0:
        if not code0:
            return None
        reply = format_reply(None, code0)
    else:
        doc = json.loads(json.dumps(spec))
        if level == 2 and rng.random() < 0.6:
            tk = doc["tasks"][-1]
            defs, tk["goal"], safety = _wrap_def(rng, tk["goal"], tk.get("safety", []))
            if safety:
                tk["safety"] = safety
            doc["defs"] = defs
        reply = format_reply(doc, world or WORLD_EMPTY)
    return req, reply, {"kind": kind, "level": level}


def load_tool_server(path: Path) -> ToolServer:
    t = ToolServer(level=0)
    t.load_osm(path.read_text(encoding="utf-8"))
    return t


def eval_texts(root: Path) -> list[str]:
    out = []
    for f in (root / "eval").glob("prompts_*.json"):
        out += [p["text"] for p in json.loads(f.read_text(encoding="utf-8"))["prompts"]]
    return out
