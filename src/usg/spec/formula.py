"""The task specification language (L2): typed atoms + temporal combinators + named definitions.

A formula is plain JSON (a ``dict``). It is DATA: it is parsed and type-checked, never executed.

    atoms        in_zone, on_surface, near_path, dist_le, dist_ge, look_at, speed_le, speed_ge, signal_is, event, true
    combinators  not, and, or, implies, eventually, always, until, then, prev
    definitions  {"op": "call", "name": "reach", "args": {...}}  (standard library or the document's own ``defs``)

Time bounds are seconds from the START OF THE TASK. Every atom has an implementation in the monitor (Python) and in
the player (TypeScript), so any well-formed formula is evaluable by construction (see ``monitor.py``).
"""
from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET
from typing import Any, Optional

MAX_NODES = 400            # size of a task formula after expansion
MAX_DEPTH = 14             # nesting depth after expansion
MAX_CALL_DEPTH = 6         # definitions calling definitions
MAX_DEFS = 12
BIG = 1.0e9                # stands for +infinity in robustness values (finite so it survives JSON)

SURFACES = ("walkable", "pedestrian_infra", "crosswalk", "road", "sidewalk", "path", "ground")
SIGNAL_STATES = ("green", "red")
ATOMS = ("true", "in_zone", "on_surface", "near_path", "dist_le", "dist_ge", "look_at", "speed_le", "speed_ge",
         "signal_is", "event")
COMBINATORS = ("not", "and", "or", "implies", "eventually", "always", "until", "then", "prev")
OPS = ATOMS + COMBINATORS + ("call",)
ZONE_KINDS = ("disc", "crossing", "crossing_side", "feature", "entity", "rect")


class SpecError(ValueError):
    """A specification error written for the model to act on (it names the JSON path and the fix)."""


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _xy(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 2 and _num(v[0]) and _num(v[1])


# ------------------------------------------------------------------ catalog (also served to the model by list_atoms)
CATALOG: dict[str, dict] = {
    "true": {"doc": "always satisfied", "fields": {}, "example": {"op": "true"}},
    "in_zone": {"doc": "the user is inside a zone; margin = metres inside the boundary",
                "fields": {"zone": "Zone"},
                "example": {"op": "in_zone", "zone": {"kind": "disc", "x": 10.0, "y": 4.0, "r": 1.5}}},
    "on_surface": {"doc": "the surface under the user's feet is of this class (qualitative: margin is +1 or -1)",
                   "fields": {"surface": "|".join(SURFACES)},
                   "example": {"op": "on_surface", "surface": "pedestrian_infra"}},
    "near_path": {"doc": "the user is within tol metres of a polyline; margin = tol - distance",
                  "fields": {"path": "[[x,y],...] (>=2 points)", "tol": "metres > 0"},
                  "example": {"op": "near_path", "path": [[0, 4], [30, 4]], "tol": 2.0}},
    "dist_le": {"doc": "distance from the user to an entity's body is <= d; margin = d - distance",
                "fields": {"entity": "entity name", "d": "metres >= 0"},
                "example": {"op": "dist_le", "entity": "Walker1", "d": 3.0}},
    "dist_ge": {"doc": "distance from the user to an entity's body is >= d; margin = distance - d",
                "fields": {"entity": "entity name", "d": "metres >= 0"},
                "example": {"op": "dist_ge", "entity": "Car1", "d": 0.3}},
    "look_at": {"doc": "the user's gaze is within `angle` degrees of an entity or a point; margin = angle - error",
                "fields": {"entity": "entity name (or use point)", "point": "[x,y] (or use entity)", "angle": "degrees in (0,180]"},
                "example": {"op": "look_at", "entity": "Car1", "angle": 35}},
    "speed_le": {"doc": "walking speed <= v m/s; margin = v - speed", "fields": {"v": "m/s >= 0"},
                 "example": {"op": "speed_le", "v": 2.0}},
    "speed_ge": {"doc": "walking speed >= v m/s; margin = speed - v", "fields": {"v": "m/s >= 0"},
                 "example": {"op": "speed_ge", "v": 0.5}},
    "signal_is": {"doc": "a traffic signal is in this state (qualitative: +1 or -1)",
                  "fields": {"signal": "signal name", "state": "green|red"},
                  "example": {"op": "signal_is", "signal": "crossing_1_ped", "state": "green"}},
    "event": {"doc": "a storyboard event has started (qualitative: +1 or -1)", "fields": {"name": "event name"},
              "example": {"op": "event", "name": "move_Car1"}},
    "not": {"doc": "negation", "fields": {"arg": "formula"}, "example": {"op": "not", "arg": {"op": "event", "name": "e"}}},
    "and": {"doc": "all hold (margin = min)", "fields": {"args": "[formula,...]"}},
    "or": {"doc": "one holds (margin = max)", "fields": {"args": "[formula,...]"}},
    "implies": {"doc": "if a then b", "fields": {"a": "formula", "b": "formula"}},
    "eventually": {"doc": "arg holds at SOME time in [start,end] seconds after now (end null = until the task ends)",
                   "fields": {"arg": "formula", "start": "s (default 0)", "end": "s or null"}},
    "always": {"doc": "arg holds at ALL times in [start,end]", "fields": {"arg": "formula", "start": "s (default 0)", "end": "s or null"}},
    "until": {"doc": "left holds until right becomes true (right must happen within [start,end])",
              "fields": {"left": "formula", "right": "formula", "start": "s", "end": "s or null"}},
    "then": {"doc": "stages in order: each stage happens at some time after the previous one",
             "fields": {"args": "[formula,...] (>=2)"}},
    "prev": {"doc": "arg at the previous sample (init = value before the first sample)",
             "fields": {"arg": "formula", "init": "true|false"}},
    "call": {"doc": "use a library or user definition", "fields": {"name": "definition name", "args": "{param: value}"}},
}

_ALLOWED_FIELDS: dict[str, set[str]] = {
    "true": set(), "in_zone": {"zone"}, "on_surface": {"surface"}, "near_path": {"path", "tol"},
    "dist_le": {"entity", "d"}, "dist_ge": {"entity", "d"}, "look_at": {"entity", "point", "angle"},
    "speed_le": {"v"}, "speed_ge": {"v"}, "signal_is": {"signal", "state"}, "event": {"name"},
    "not": {"arg"}, "and": {"args"}, "or": {"args"}, "implies": {"a", "b"},
    "eventually": {"arg", "start", "end"}, "always": {"arg", "start", "end"},
    "until": {"left", "right", "start", "end"}, "then": {"args"}, "prev": {"arg", "init"}, "call": {"name", "args"},
}


def P(name: str) -> dict:
    """A parameter placeholder inside a definition body."""
    return {"param": name}


# ------------------------------------------------------------------ standard library (definitions written in the language itself)
def _ev(arg, end=None, start=0):
    return {"op": "eventually", "arg": arg, "start": start, "end": end}


def _al(arg, end=None, start=0):
    return {"op": "always", "arg": arg, "start": start, "end": end}


STD_LIB: dict[str, dict] = {
    "reach": {"doc": "get inside a zone at some time", "params": ["zone"],
              "body": _ev({"op": "in_zone", "zone": P("zone")})},
    "reach_within": {"doc": "get inside a zone within `seconds`", "params": ["zone", "seconds"],
                     "body": _ev({"op": "in_zone", "zone": P("zone")}, end=P("seconds"))},
    "hold": {"doc": "stay inside a zone for `seconds`", "params": ["zone", "seconds"],
             "body": _al({"op": "in_zone", "zone": P("zone")}, end=P("seconds"))},
    "wait_for_green": {"doc": "stay inside a zone until the signal turns green", "params": ["zone", "signal"],
                       "body": {"op": "until", "left": {"op": "in_zone", "zone": P("zone")},
                                "right": {"op": "signal_is", "signal": P("signal"), "state": "green"},
                                "start": 0, "end": None}},
    "look": {"doc": "look at an entity (within `angle` degrees) within `seconds`", "params": ["entity", "angle", "seconds"],
             "body": _ev({"op": "look_at", "entity": P("entity"), "angle": P("angle")}, end=P("seconds"))},
    "look_point": {"doc": "look at a point within `seconds`", "params": ["point", "angle", "seconds"],
                   "body": _ev({"op": "look_at", "point": P("point"), "angle": P("angle")}, end=P("seconds"))},
    "follow": {"doc": "stay within d metres of an entity for `seconds`", "params": ["entity", "d", "seconds"],
               "body": _al({"op": "dist_le", "entity": P("entity"), "d": P("d")}, end=P("seconds"))},
    "keep_clear": {"doc": "stay at least d metres from an entity for `seconds`", "params": ["entity", "d", "seconds"],
                   "body": _al({"op": "dist_ge", "entity": P("entity"), "d": P("d")}, end=P("seconds"))},
    "pace": {"doc": "walk between vmin and vmax m/s for `seconds`", "params": ["vmin", "vmax", "seconds"],
             "body": _al({"op": "and", "args": [{"op": "speed_ge", "v": P("vmin")}, {"op": "speed_le", "v": P("vmax")}]},
                         end=P("seconds"))},
    "collision_free": {"doc": "never come closer than r metres to an entity's body", "params": ["entity", "r"],
                       "body": _al({"op": "dist_ge", "entity": P("entity"), "d": P("r")})},
    "stay_on": {"doc": "never be off a surface class for more than 1 s", "params": ["surface"],
                "body": _al(_ev({"op": "on_surface", "surface": P("surface")}, end=1.0))},
    "stay_near_path": {"doc": "never be farther than tol from a path for more than 1 s", "params": ["path", "tol"],
                       "body": _al(_ev({"op": "near_path", "path": P("path"), "tol": P("tol")}, end=1.0))},
    "obey_signal": {"doc": "only step into the zone while the signal is green", "params": ["zone", "signal"],
                    "body": _al({"op": "implies",
                                 "a": {"op": "and", "args": [{"op": "in_zone", "zone": P("zone")},
                                                             {"op": "prev", "arg": {"op": "not", "arg": {"op": "in_zone", "zone": P("zone")}}, "init": True}]},
                                 "b": {"op": "signal_is", "signal": P("signal"), "state": "green"}})},
    "no_event": {"doc": "this storyboard event must never start", "params": ["name"],
                 "body": _al({"op": "not", "arg": {"op": "event", "name": P("name")}})},
    "cross": {"doc": "get to the far side of a crossing", "params": ["far_zone"],
              "body": _ev({"op": "in_zone", "zone": P("far_zone")})},
}


# ------------------------------------------------------------------ structural check
def _bad(path: str, msg: str) -> SpecError:
    return SpecError(f"{path}: {msg}")


def check_zone(z: Any, path: str) -> None:
    if not isinstance(z, dict) or z.get("kind") not in ZONE_KINDS:
        raise _bad(path, f"zone must be an object with kind in {list(ZONE_KINDS)}, e.g. "
                         f"{{\"kind\":\"disc\",\"x\":10,\"y\":4,\"r\":1.5}} (got {z!r})")
    k = z["kind"]
    need = {"disc": ("x", "y", "r"), "crossing": ("id",), "crossing_side": ("id", "side"), "feature": ("id",),
            "entity": ("name", "r"), "rect": ("cx", "cy", "h", "hl", "hw")}[k]
    for f in need:
        if f not in z:
            raise _bad(path, f"zone kind '{k}' needs the field '{f}'")
    for f in ("x", "y", "r", "cx", "cy", "h", "hl", "hw", "margin"):
        if f in z and not _num(z[f]):
            raise _bad(path, f"zone field '{f}' must be a number")
    for f in ("r", "hl", "hw"):
        if f in z and z[f] <= 0:
            raise _bad(path, f"zone field '{f}' must be > 0")
    if k == "crossing_side" and z["side"] not in ("start", "end"):
        raise _bad(path, "zone side must be 'start' or 'end'")


def _is_param(v: Any) -> bool:
    return isinstance(v, dict) and set(v) == {"param"}


def _interval(n: dict, path: str) -> None:
    a, b = n.get("start", 0), n.get("end")
    if _is_param(a) or _is_param(b):
        return                                   # validated after substitution
    if not _num(a) or a < 0:
        raise _bad(path, "'start' must be a number >= 0 (seconds after now)")
    if b is not None and (not _num(b) or b < a):
        raise _bad(path, "'end' must be null or a number >= start")


def check_node(n: Any, path: str = "$", params: Optional[set] = None) -> None:
    """Structure/type check of ONE node and its children (definitions are not expanded here)."""
    if isinstance(n, dict) and set(n) == {"param"}:
        if params is None or n["param"] not in params:
            raise _bad(path, f"unknown parameter '{n['param']}'")
        return
    if not isinstance(n, dict) or "op" not in n:
        raise _bad(path, f"a formula node is an object with an 'op' field (got {n!r})")
    op = n["op"]
    if op not in OPS:
        raise _bad(path, f"unknown op '{op}'. Atoms: {list(ATOMS)}; combinators: {list(COMBINATORS)}; or op 'call'")
    extra = set(n) - {"op"} - _ALLOWED_FIELDS[op]
    if extra:
        raise _bad(path, f"op '{op}' does not take {sorted(extra)}; allowed: {sorted(_ALLOWED_FIELDS[op])}")

    def val(key, test, what):
        if key not in n:
            raise _bad(path, f"op '{op}' needs '{key}' ({what})")
        v = n[key]
        if isinstance(v, dict) and set(v) == {"param"}:
            check_node(v, f"{path}.{key}", params)
            return
        if not test(v):
            raise _bad(f"{path}.{key}", f"must be {what} (got {v!r})")

    if op == "true":
        return
    if op == "in_zone":
        if "zone" not in n:
            raise _bad(path, "op 'in_zone' needs 'zone'")
        if not (isinstance(n["zone"], dict) and set(n["zone"]) == {"param"}):
            check_zone(n["zone"], f"{path}.zone")
        else:
            check_node(n["zone"], f"{path}.zone", params)
    elif op == "on_surface":
        val("surface", lambda v: v in SURFACES, f"one of {list(SURFACES)}")
    elif op == "near_path":
        val("path", lambda v: isinstance(v, list) and len(v) >= 2 and all(_xy(p) for p in v), "a list of >= 2 [x,y] points")
        val("tol", lambda v: _num(v) and v > 0, "a number > 0")
    elif op in ("dist_le", "dist_ge"):
        val("entity", lambda v: isinstance(v, str) and v, "an entity name")
        val("d", lambda v: _num(v) and v >= 0, "a number >= 0")
    elif op == "look_at":
        if ("entity" in n) == ("point" in n):
            raise _bad(path, "op 'look_at' needs exactly one of 'entity' or 'point'")
        if "entity" in n:
            val("entity", lambda v: isinstance(v, str) and v, "an entity name")
        else:
            val("point", _xy, "[x,y]")
        val("angle", lambda v: _num(v) and 0 < v <= 180, "degrees in (0,180]")
    elif op in ("speed_le", "speed_ge"):
        val("v", lambda v: _num(v) and v >= 0, "a number >= 0")
    elif op == "signal_is":
        val("signal", lambda v: isinstance(v, str) and v, "a signal name")
        val("state", lambda v: v in SIGNAL_STATES, f"one of {list(SIGNAL_STATES)}")
    elif op == "event":
        val("name", lambda v: isinstance(v, str) and v, "an event name")
    elif op in ("not", "eventually", "always", "prev"):
        if "arg" not in n:
            raise _bad(path, f"op '{op}' needs 'arg'")
        check_node(n["arg"], f"{path}.arg", params)
        if op in ("eventually", "always"):
            _interval(n, path)
        if op == "prev" and "init" in n and not isinstance(n["init"], bool):
            raise _bad(path, "'init' must be true or false")
    elif op in ("and", "or", "then"):
        a = n.get("args")
        if not isinstance(a, list) or len(a) < (2 if op == "then" else 1):
            raise _bad(path, f"op '{op}' needs 'args': a list of {'>= 2' if op == 'then' else '>= 1'} formulas")
        for i, c in enumerate(a):
            check_node(c, f"{path}.args[{i}]", params)
    elif op == "implies":
        for k in ("a", "b"):
            if k not in n:
                raise _bad(path, "op 'implies' needs 'a' and 'b'")
            check_node(n[k], f"{path}.{k}", params)
    elif op == "until":
        for k in ("left", "right"):
            if k not in n:
                raise _bad(path, "op 'until' needs 'left' and 'right'")
            check_node(n[k], f"{path}.{k}", params)
        _interval(n, path)
    elif op == "call":
        if not isinstance(n.get("name"), str):
            raise _bad(path, "op 'call' needs a 'name'")
        if not isinstance(n.get("args", {}), dict):
            raise _bad(path, "op 'call' needs 'args' as an object {param: value}")


def check_defs(defs: Any) -> None:
    if defs in (None, {}):
        return
    if not isinstance(defs, dict) or len(defs) > MAX_DEFS:
        raise SpecError(f"defs: must be an object with at most {MAX_DEFS} definitions")
    for name, d in defs.items():
        if not (isinstance(name, str) and name.replace("_", "").isalnum() and name[0].isalpha()):
            raise SpecError(f"defs.{name}: definition names are letters/digits/underscore")
        if name in STD_LIB or name in OPS:
            raise SpecError(f"defs.{name}: name clashes with a library definition or an op; pick another name")
        if not isinstance(d, dict) or "body" not in d:
            raise SpecError(f"defs.{name}: needs {{\"params\": [...], \"body\": formula}}")
        ps = d.get("params", [])
        if not (isinstance(ps, list) and all(isinstance(p, str) for p in ps)):
            raise SpecError(f"defs.{name}.params must be a list of names")
        check_node(d["body"], f"defs.{name}.body", set(ps))


# ------------------------------------------------------------------ expansion (definitions -> core formula)
def _subst(node: Any, args: dict, name: str) -> Any:
    if isinstance(node, dict):
        if set(node) == {"param"}:
            if node["param"] not in args:
                raise SpecError(f"call '{name}': missing argument '{node['param']}'")
            return copy.deepcopy(args[node["param"]])
        return {k: _subst(v, args, name) for k, v in node.items()}
    if isinstance(node, list):
        return [_subst(v, args, name) for v in node]
    return node


def _then(args: list) -> dict:
    if len(args) == 1:
        return {"op": "eventually", "arg": args[0], "start": 0, "end": None}
    return {"op": "eventually", "arg": {"op": "and", "args": [args[0], _then(args[1:])]}, "start": 0, "end": None}


def expand(node: Any, defs: Optional[dict] = None, *, _stack: tuple = (), _path: str = "$") -> dict:
    """Replace every ``call`` and ``then`` by core operators. Raises SpecError on unknown/recursive/too-deep calls."""
    defs = defs or {}
    if isinstance(node, dict) and "op" in node:
        op = node["op"]
        if op == "call":
            name = node["name"]
            d = defs.get(name) or STD_LIB.get(name)
            if d is None:
                raise _bad(_path, f"unknown definition '{name}'. Library: {sorted(STD_LIB)}; yours: {sorted(defs)}")
            if name in _stack:
                raise _bad(_path, f"definition '{name}' calls itself (recursion is not allowed): {' -> '.join(_stack + (name,))}")
            if len(_stack) >= MAX_CALL_DEPTH:
                raise _bad(_path, f"definitions nested more than {MAX_CALL_DEPTH} deep")
            params = d.get("params", [])
            args = node.get("args", {})
            missing = [p for p in params if p not in args]
            extra = [a for a in args if a not in params]
            if missing or extra:
                raise _bad(_path, f"call '{name}' needs arguments {params}" +
                           (f"; missing {missing}" if missing else "") + (f"; unexpected {extra}" if extra else ""))
            body = _subst(d["body"], args, name)
            return expand(body, defs, _stack=_stack + (name,), _path=f"{_path}<{name}>")
        out: dict = {"op": op}
        for k, v in node.items():
            if k == "op":
                continue
            if k == "args" and op in ("and", "or", "then"):
                out[k] = [expand(c, defs, _stack=_stack, _path=f"{_path}.args[{i}]") for i, c in enumerate(v)]
            elif k in ("arg", "a", "b", "left", "right"):
                out[k] = expand(v, defs, _stack=_stack, _path=f"{_path}.{k}")
            else:
                out[k] = copy.deepcopy(v)
        if op == "then":
            return _then(out["args"])
        if op in ("eventually", "always", "until"):
            out.setdefault("start", 0)
            out.setdefault("end", None)
        if op == "prev":
            out.setdefault("init", True)
        return out
    return node


def measure(node: dict) -> tuple[int, int]:
    """(node count, depth) of a core formula."""
    kids = []
    for k in ("arg", "a", "b", "left", "right"):
        if k in node:
            kids.append(node[k])
    kids += node.get("args", []) if node["op"] in ("and", "or") else []
    if not kids:
        return 1, 1
    sizes = [measure(c) for c in kids]
    return 1 + sum(s for s, _ in sizes), 1 + max(d for _, d in sizes)


def check_core(node: dict, path: str = "formula") -> None:
    n, d = measure(node)
    if n > MAX_NODES:
        raise SpecError(f"{path}: formula has {n} nodes after expansion (limit {MAX_NODES}); simplify it")
    if d > MAX_DEPTH:
        raise SpecError(f"{path}: formula is {d} levels deep after expansion (limit {MAX_DEPTH}); simplify it")


def prepare(node: Any, defs: Optional[dict] = None, path: str = "formula") -> dict:
    """Check structure, expand definitions, check size/depth. The result is a CORE formula (no call/then)."""
    check_node(node, path)
    core = expand(node, defs, _path=path)
    check_node(core, path)                       # again after substitution: catches wrong argument values
    check_core(core, path)
    return core


# ------------------------------------------------------------------ walking a core formula
def walk(node: dict):
    yield node
    for k in ("arg", "a", "b", "left", "right"):
        if k in node:
            yield from walk(node[k])
    if node["op"] in ("and", "or"):
        for c in node["args"]:
            yield from walk(c)


def atoms_in(node: dict) -> list[dict]:
    return [n for n in walk(node) if n["op"] in ATOMS]


def entities_in(node: dict) -> set[str]:
    out = set()
    for n in atoms_in(node):
        if n["op"] in ("dist_le", "dist_ge") or (n["op"] == "look_at" and "entity" in n):
            out.add(n["entity"])
        if n["op"] == "in_zone" and n["zone"].get("kind") == "entity":
            out.add(n["zone"]["name"])
    return out


def signals_in(node: dict) -> set[str]:
    return {n["signal"] for n in atoms_in(node) if n["op"] == "signal_is"}


def events_in(node: dict) -> set[str]:
    return {n["name"] for n in atoms_in(node) if n["op"] == "event"}


def zones_in(node: dict) -> list[dict]:
    return [n["zone"] for n in atoms_in(node) if n["op"] == "in_zone"]


# ------------------------------------------------------------------ resolving map references (-> numeric, self-contained)
def resolve_zone(z: dict, q, path: str = "zone") -> dict:
    """Turn a symbolic zone into numbers: disc{x,y,r} | rect{cx,cy,h,hl,hw} | entity{name,r}. ``q`` is a MapQuery."""
    k = z["kind"]
    if k in ("disc", "rect", "entity"):
        return dict(z)
    m = q._m
    try:
        if k == "crossing":
            c = m.get(z["id"])
            if c is None or getattr(c, "kind", "") != "crossing":
                raise KeyError
            margin = float(z.get("margin", 0.0))
            return {"kind": "rect", "cx": c.pos[0], "cy": c.pos[1], "h": c.heading,
                    "hl": c.length / 2 + margin, "hw": c.width / 2 + margin}
        if k == "crossing_side":
            p = q.crossing_side(z["id"], z["side"], float(z.get("inset", 1.0)))
            return {"kind": "disc", "x": p.x, "y": p.y, "r": float(z.get("r", 1.5))}
        if k == "feature":
            (x, y), _h = m.feature_point(z["id"], float(z.get("u", 0.5)), float(z.get("v", 0.0)))
            return {"kind": "disc", "x": x, "y": y, "r": float(z.get("r", 2.0))}
    except KeyError:
        raise _bad(path, f"unknown map reference '{z.get('id')}' for zone kind '{k}'; use list_features to see valid ids") from None
    raise _bad(path, f"unsupported zone kind {k}")


def resolve(node: dict, q) -> dict:
    """Copy of a core formula with zones resolved against the map."""
    out = copy.deepcopy(node)
    for n in walk(out):
        if n["op"] == "in_zone":
            n["zone"] = resolve_zone(n["zone"], q)
    return out


# ------------------------------------------------------------------ pretty printing (for the UI and the paper)
def describe(node: dict) -> str:
    op = node["op"]
    iv = ""
    if op in ("eventually", "always", "until"):
        b = node.get("end")
        iv = f"[{node.get('start', 0):g},{'inf' if b is None else format(b, 'g')}]"
    if op == "true":
        return "true"
    if op == "in_zone":
        z = node["zone"]
        if z["kind"] == "disc":
            return f"in_zone(disc({z['x']:.1f},{z['y']:.1f};r={z['r']:g}))"
        if z["kind"] == "rect":
            return f"in_zone(rect({z['cx']:.1f},{z['cy']:.1f}))"
        return f"in_zone({z.get('name') or z.get('id')})"
    if op == "on_surface":
        return f"on_surface({node['surface']})"
    if op == "near_path":
        return f"near_path({len(node['path'])} pts, tol={node['tol']:g})"
    if op in ("dist_le", "dist_ge"):
        return f"dist({node['entity']}){'<=' if op == 'dist_le' else '>='}{node['d']:g}"
    if op == "look_at":
        return f"look_at({node.get('entity') or node.get('point')}, {node['angle']:g}deg)"
    if op in ("speed_le", "speed_ge"):
        return f"speed{'<=' if op == 'speed_le' else '>='}{node['v']:g}"
    if op == "signal_is":
        return f"{node['signal']}={node['state']}"
    if op == "event":
        return f"event({node['name']})"
    if op == "not":
        return f"not {describe(node['arg'])}"
    if op in ("and", "or"):
        return "(" + f" {op} ".join(describe(c) for c in node["args"]) + ")"
    if op == "implies":
        return f"({describe(node['a'])} -> {describe(node['b'])})"
    if op == "prev":
        return f"prev({describe(node['arg'])})"
    if op in ("eventually", "always"):
        return f"{op}{iv}({describe(node['arg'])})"
    if op == "until":
        return f"({describe(node['left'])} until{iv} {describe(node['right'])})"
    return op


# ------------------------------------------------------------------ XML (carried in the <VRTask><Spec> element)
_SCALARS = {"surface", "tol", "entity", "d", "angle", "v", "signal", "state", "name", "start", "end", "init", "label"}


def to_xml(node: dict) -> ET.Element:
    op = node["op"]
    e = ET.Element("F", op=op)
    for k in _SCALARS & set(node):
        v = node[k]
        if v is None:
            continue
        e.set(k, ("true" if v else "false") if isinstance(v, bool) else format(v, ".10g") if isinstance(v, (int, float)) else str(v))
    if op == "look_at" and "point" in node:
        e.set("px", format(node["point"][0], ".10g"))
        e.set("py", format(node["point"][1], ".10g"))
    if op == "near_path":
        for p in node["path"]:
            ET.SubElement(e, "P", x=format(p[0], ".10g"), y=format(p[1], ".10g"))
    if op == "in_zone":
        z = node["zone"]
        ze = ET.SubElement(e, "Zone", kind=z["kind"])
        for k, v in z.items():
            if k != "kind":
                ze.set(k, format(v, ".10g") if isinstance(v, (int, float)) else str(v))
    for k in ("arg", "a", "b", "left", "right"):
        if k in node:
            e.append(to_xml(node[k]))
    if op in ("and", "or"):
        for c in node["args"]:
            e.append(to_xml(c))
    return e


def from_xml(e: ET.Element) -> dict:
    """Inverse of ``to_xml`` (used by the tests and by tools that read a scenario back)."""
    op = e.get("op", "")
    n: dict = {"op": op}
    num_keys = {"tol", "d", "angle", "v", "start", "end"}
    for k in _SCALARS:
        if e.get(k) is not None:
            v = e.get(k)
            n[k] = (v == "true") if k == "init" else float(v) if k in num_keys else v
    if op in ("eventually", "always", "until"):
        n.setdefault("start", 0.0)
        n["end"] = n.get("end")
    if op == "look_at" and e.get("px") is not None:
        n["point"] = [float(e.get("px")), float(e.get("py"))]
    if op == "near_path":
        n["path"] = [[float(p.get("x")), float(p.get("y"))] for p in e.findall("P")]
    if op == "in_zone":
        ze = e.find("Zone")
        z: dict = {"kind": ze.get("kind")}
        for k, v in ze.attrib.items():
            if k == "kind":
                continue
            try:
                z[k] = float(v)
            except ValueError:
                z[k] = v
        n["zone"] = z
    kids = e.findall("F")
    if op in ("not", "eventually", "always", "prev"):
        n["arg"] = from_xml(kids[0])
    elif op == "implies":
        n["a"], n["b"] = from_xml(kids[0]), from_xml(kids[1])
    elif op == "until":
        n["left"], n["right"] = from_xml(kids[0]), from_xml(kids[1])
    elif op in ("and", "or"):
        n["args"] = [from_xml(k) for k in kids]
    return n


# ------------------------------------------------------------------ JSON schema for grammar-constrained decoding
def json_schema() -> dict:
    """A (non-recursive-depth-limited) JSON Schema of a specification document, for servers that constrain decoding."""
    f = {"$ref": "#/$defs/formula"}
    ops = list(OPS)
    return {
        "$defs": {
            "formula": {
                "type": "object",
                "properties": {"op": {"enum": ops}, "arg": f, "a": f, "b": f, "left": f, "right": f,
                               "args": {"type": "array", "items": f}, "start": {"type": "number"},
                               "end": {"type": ["number", "null"]}, "zone": {"type": "object"},
                               "surface": {"type": "string"}, "entity": {"type": "string"}, "name": {"type": "string"},
                               "signal": {"type": "string"}, "state": {"type": "string"}, "d": {"type": "number"},
                               "v": {"type": "number"}, "tol": {"type": "number"}, "angle": {"type": "number"},
                               "path": {"type": "array"}, "point": {"type": "array"}, "init": {"type": "boolean"}},
                "required": ["op"],
            }
        },
        "type": "object",
        "properties": {
            "defs": {"type": "object"},
            "tasks": {"type": "array", "minItems": 1, "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "instruction": {"type": "string"},
                               "goal": f, "safety": {"type": "array", "items": f},
                               "timeout": {"type": "object", "properties": {"initial": {"type": "number"}, "baseline": {"type": "number"}}},
                               "after": {"type": "array", "items": {"type": "string"}},
                               "group": {"type": "string"}, "mode": {"enum": ["sequential", "parallel", "independent"]},
                               "required": {"type": "boolean"}},
                "required": ["name", "instruction", "goal"]}},
        },
        "required": ["tasks"],
    }
