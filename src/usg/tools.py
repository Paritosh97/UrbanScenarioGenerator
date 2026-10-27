"""The agent's tool server: grounded map queries plus script submission.

Everything the agent can do against the map or the scenario goes through ``ToolServer.call``.
Return values are small, plain JSON so a 3-7B model can read them. Arguments are parsed leniently
(a point may be ``[0, 0]``, ``"[0, 0]"`` or ``"0,0"``; numbers may arrive as strings) and every error says
what was wrong and shows a working example call.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from . import assist as assist_mod
from . import esmini as esmini_mod
from . import geo, osm, xodr
from .dsl import MapQuery
from .mapmodel import MapModel
from .sandbox import run_script
from .scenario_types import ARCHETYPES, AXIS_DEFAULTS, classify
from .spec import formula as F
from .spec.document import check_document, feedback_text
from . import grounding

PROMPTS = Path(__file__).parent / "agent" / "prompts"
MAX_ITEMS = 25


def prompt_text(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def tool_specs(level: int = 0) -> list[dict]:
    """LLM-readable tool catalogue; ``example`` is a call that works on any map (shown in prompts and errors).

    level 0: the model writes a script that calls task helpers (go_to / cross / follow_path).
    level 1: the model first submits a task SPECIFICATION built from the library definitions, then a world script.
    level 2: like level 1 and the model may also define its own definitions.
    """
    spec_tools = [
        {"name": "list_atoms", "doc": "The specification language: atoms, combinators and library definitions with examples. Takes no arguments.",
         "example": {}},
        {"name": "submit_spec", "doc": "Check and store your task specification (JSON with a 'tasks' list). Returns OK plus what your script must "
                                       "create, or the exact errors to fix. Do this BEFORE submit_script.",
         "example": {"tasks": [{"name": "reach_stop", "instruction": "Walk to the bus stop.",
                                "goal": {"op": "call", "name": "reach", "args": {"zone": {"kind": "disc", "x": 20, "y": 4.5, "r": 2}}},
                                "timeout": {"initial": 60, "baseline": 90}}]}},
    ] if level >= 1 else []
    return _base_specs(level) if level == 0 else spec_tools + _base_specs(level)


def _base_specs(level: int) -> list[dict]:
    submit = {"name": "submit_script", "doc": ("Run + validate your scenario script. Returns OK or the exact errors to fix. "
                                              "Put the code in a ```python block instead of JSON.") if level == 0 else
              ("Run + validate your WORLD-BUILDING script (it must call scenario.apply_spec(SPEC)). Returns OK or the exact errors to fix. "
               "Put the code in a ```python block instead of JSON."), "example": None}
    return [
        {"name": "get_map_overview", "doc": "Size of the map and counts of roads, crossings, signals, props. Takes no arguments.",
         "example": {}},
        {"name": "list_features",
         "doc": "List map features with ids and positions (metres; x = east, y = north). kind is one of: crossing, road, junction, "
                "signal, bus_stop, prop, path, building, kerb_slots. Optional: control (zebra|signals) for crossings, ptype "
                "(waste_basket|bench|tree|street_lamp|bollard) for props, road for kerb_slots, near as [x, y] with radius in metres, limit.",
         "example": {"kind": "crossing", "control": "zebra"}},
        {"name": "get_feature", "doc": "Details and position of one feature by id.", "example": {"id": "crossing_1"}},
        {"name": "check_point", "doc": "Surface at a point: road, crosswalk, sidewalk, path, building, water or ground.",
         "example": {"x": 12.0, "y": -4.5}},
        {"name": "plan_route", "doc": "Pedestrian route (length, crossings used, waypoints) between two points given as [x, y].",
         "example": {"from": [20, 4.5], "to": [20, -4.5]}},
        {"name": "list_scenario_types", "doc": "The 7 scenario archetypes and their requirements. Takes no arguments.", "example": {}},
        {"name": "get_scenario_template", "doc": "A complete reference script for an archetype id.", "example": {"type": "dyn_nav"}},
        {"name": "record_plan", "doc": "Save your plan (type, entities, tasks, dynamics, hud texts) before writing code.",
         "example": {"plan": {"type": "dyn_nav", "crossing": "crossing_3", "vehicle": "Car1 at 8 m/s"}}},
        submit,
    ]


class ToolArgError(ValueError):
    """The model passed a bad argument; the message is shown to it verbatim."""


def _num(v: Any, name: str, default: Optional[float] = None) -> float:
    if v is None or v == "":
        if default is None:
            raise ToolArgError(f"'{name}' is required and must be a number")
        return float(default)
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ToolArgError(f"'{name}' must be a number, got {v!r}") from None


def _pt(v: Any, name: str) -> tuple[float, float]:
    if isinstance(v, dict):
        v = [v.get("x"), v.get("y")]
    if isinstance(v, str):
        v = re.findall(r"-?\d+(?:\.\d+)?", v)
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ToolArgError(f"'{name}' must be a point like [x, y] (two numbers in metres), got {v!r}")
    return (_num(v[0], name), _num(v[1], name))


def _usage(name: str) -> str:
    for t in tool_specs(2):
        if t["name"] == name and t["example"] is not None:
            return f'Example: <tool name="{name}">{json.dumps(t["example"])}</tool>'
    return ""


def _world_names(doc) -> set:
    """Entity and signal names a specification refers to (they must exist in the world script)."""
    out: set = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("entity", "signal") and isinstance(v, str):
                    out.add(v)
                elif k == "name" and x.get("kind") == "entity" and isinstance(v, str):
                    out.add(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(doc.get("tasks", []))
    return out


class ToolServer:
    def __init__(self, level: int = 0) -> None:
        self.level = level                       # 0 script only | 1 specification from the library | 2 + own definitions
        self.prompt = ""                         # the user's request (set by the agent loop): used by the grounding checks
        self.last_spec: Optional[dict] = None    # last submitted specification / script, accepted or not (shown in the UI editors)
        self.last_code: Optional[str] = None
        self.vision = False                      # attach an annotated top-down map image to the first message (needs a vision model)
        self.spec: Optional[dict] = None         # the accepted specification document (levels 1-2)
        self.spec_needs: dict = {}               # what that specification needs in the world (entities, signals), for the assist
        self.spec_attempts = 0
        self.assist = "off"                      # "off" | "world" | "fallback": deterministic safety nets (see usg.assist); every result records its tier
        self._fallback_mode = False              # set while the harness submits the fallback: validity is guaranteed, the request check is not applied
        self.esmini: Optional[Path] = None       # if set, a scenario is accepted only if esmini loads and runs it (the exported file is a standard one)
        self.model: Optional[MapModel] = None
        self.q: Optional[MapQuery] = None
        self.plan: Optional[dict] = None
        self.result: Optional[dict] = None
        self.attempts = 0
        self._tmp = Path(tempfile.mkdtemp(prefix="usg_tools_"))
        self.map_path = self._tmp / "scene_map.json"

    # ----------------------------------------------------------- lifecycle
    def load_osm(self, osm_text: str, bbox: Optional[list[float]] = None) -> dict:
        built = osm.build_map(osm_text, tuple(bbox) if bbox else None)
        # validate against exactly what the sandbox child loads (JSON-rounded coordinates)
        self.model = MapModel.from_dict(json.loads(json.dumps(built.to_dict())))
        return self._after_load()

    def load_map_json(self, map_json: str) -> dict:
        self.model = MapModel.from_dict(json.loads(map_json))
        return self._after_load()

    def _after_load(self) -> dict:
        assert self.model is not None
        self.q = MapQuery(self.model)
        self.model.save(self.map_path)          # the sandboxed child process loads the map from here
        self.plan = self.result = None
        self.spec = None
        self.last_spec = self.last_code = None
        self.attempts = self.spec_attempts = 0
        return {"overview": self.q.overview()}

    def scene_map_json(self) -> str:
        assert self.model is not None
        return json.dumps(self.model.to_dict())

    def xodr_text(self) -> str:
        assert self.model is not None
        path = self._tmp / "map.xodr"
        spec = (self.result or {}).get("spec") or {}
        xodr.export_xodr(self.model, path, virtual=[(v["signal"], v["crossing"]) for v in spec.get("virtual_signals", [])])
        return path.read_text(encoding="utf-8")

    # ----------------------------------------------------------- tools
    def call(self, name: str, args: Optional[dict] = None) -> dict:
        args = args if isinstance(args, dict) else {}
        try:
            fn = getattr(self, "t_" + name, None)
            if fn is None:
                return {"ok": False, "error": f"unknown tool '{name}'. Tools: {[t['name'] for t in tool_specs(self.level)]}"}
            if self.q is None and name not in ("list_scenario_types", "get_scenario_template", "list_atoms"):
                return {"ok": False, "error": "no map loaded"}
            return {"ok": True, **fn(args)}
        except ToolArgError as e:
            return {"ok": False, "error": f"bad argument: {e}. {_usage(name)}".strip()}
        except KeyError as e:
            return {"ok": False, "error": f"missing or unknown value {e}. {_usage(name)}".strip()}
        except Exception as e:                                # tool errors go back to the LLM, never crash the loop
            return {"ok": False, "error": f"{type(e).__name__}: {e}. {_usage(name)}".strip()}

    def t_get_map_overview(self, a: dict) -> dict:
        q = self.q
        return {"overview": q.overview(),
                "signalised_crossings": [c["id"] for c in q.crossings("signals")],
                "zebra_crossings": [c["id"] for c in q.crossings("zebra")],
                "bus_stops": [b["id"] for b in q.bus_stops()],
                "prop_types": sorted({p["type"] for p in q.props()})}

    def t_list_features(self, a: dict) -> dict:
        q = self.q
        kind = str(a.get("kind", "")).strip().lower()
        kinds = ["crossing", "road", "junction", "signal", "bus_stop", "prop", "path", "building", "kerb_slots"]
        if kind not in kinds:
            raise ToolArgError(f"'kind' must be one of {kinds}, got {a.get('kind')!r}")
        limit = int(_num(a.get("limit"), "limit", 12))
        radius = _num(a.get("radius"), "radius", 80)
        near = _pt(a["near"], "near") if a.get("near") not in (None, "", []) else None
        if kind == "crossing":
            control = a.get("control")
            items, key = q.crossings(control if control in ("zebra", "signals", "uncontrolled") else None), (lambda i: i["center"])
        elif kind == "road":
            items, key = q.roads(), (lambda i: i["start"])
        elif kind == "junction":
            items, key = q.junctions(), (lambda i: i["pos"])
        elif kind == "signal":
            items, key = q.signals(), (lambda i: i["pos"])
        elif kind == "bus_stop":
            items, key = q.bus_stops(), (lambda i: i["pos"])
        elif kind == "prop":
            items, key = q.props(a.get("ptype")), (lambda i: i["pos"])
        elif kind == "path":
            items, key = q.paths(), (lambda i: i["start"])
        elif kind == "building":
            items, key = q.buildings(), (lambda i: i["center"])
        else:                                                      # kerb_slots
            if not a.get("road"):
                raise ToolArgError("kind=kerb_slots needs 'road' (a road id such as \"road_2\")")
            items = [{"slot": p.label, "x": round(p.x, 1), "y": round(p.y, 1), "heading": round(p.h, 2)}
                     for p in q.kerb_slots(str(a["road"]), str(a.get("side", "right")), _num(a.get("spacing"), "spacing", 7.0))]
            return {"count": len(items), "items": items[:limit], "note": "use MAP.kerb_slots(road, side) in code"}
        if near:
            items = sorted((i for i in items if geo.dist(tuple(key(i)), near) <= radius),
                           key=lambda i: geo.dist(tuple(key(i)), near))
        return {"count": len(items), "items": items[:min(limit, MAX_ITEMS)]}

    def t_get_feature(self, a: dict) -> dict:
        fid = a.get("id")
        if not fid:
            raise ToolArgError("'id' is required (a feature id such as \"crossing_1\")")
        if self.model.get(str(fid)) is None:
            raise ToolArgError(f"no feature with id {fid!r}. Get ids from list_features")
        f = self.q.feature(str(fid))
        o = self.model.get(str(fid))
        if hasattr(o, "control"):
            f["control"] = o.control
            f["road"] = o.road
        return {"feature": f}

    def t_check_point(self, a: dict) -> dict:
        p = (_num(a.get("x"), "x"), _num(a.get("y"), "y"))
        rd, s, t, d = self.model.nearest_road(p)
        return {"surface": self.model.surface_at(p), "nearest_road": rd.id if rd else None,
                "road_s": round(s, 1), "dist_to_road_centre": round(d, 1)}

    def t_plan_route(self, a: dict) -> dict:
        fr, to = _pt(a.get("from"), "from"), _pt(a.get("to"), "to")
        r = self.model.ped_graph.route(fr, to)
        if r is None:
            return {"route": None, "note": "no pedestrian route"}
        wp = r["waypoints"]
        step = max(1, len(wp) // 12)
        return {"length_m": round(r["length"], 1), "est_time_s_at_1.2mps": round(r["length"] / 1.2),
                "crossings": r["crossings"], "waypoints": [[round(p[0], 1), round(p[1], 1)] for p in wp[::step]]}

    def t_list_scenario_types(self, a: dict) -> dict:
        return {"types": [{"id": i, "title": t["title"], "description": t["description"],
                           "requirements": t["requirements"],
                           "axes": {k: v for k, v in t["axes"].items() if v != AXIS_DEFAULTS[k]}}
                          for i, t in ARCHETYPES.items()],
                "note": "every type is a named point on constraint axes; a scenario may combine several constraints"}

    def t_get_scenario_template(self, a: dict) -> dict:
        tid = str(a.get("type", "")).strip()
        if tid not in ARCHETYPES:
            raise ToolArgError(f"'type' must be one of {sorted(ARCHETYPES)}, got {a.get('type')!r}")
        return {"type": tid, "script": ARCHETYPES[tid]["template"]}

    def t_record_plan(self, a: dict) -> dict:
        self.plan = a.get("plan") or a
        return {"saved": True, "hint": "now call get_scenario_template for your type, adapt it, and call submit_script"}

    def t_list_atoms(self, a: dict) -> dict:
        atoms = {k: {"meaning": v["doc"], "fields": v["fields"], **({"example": v["example"]} if "example" in v else {})}
                 for k, v in F.CATALOG.items() if k in F.ATOMS}
        comb = {k: {"meaning": v["doc"], "fields": v["fields"]} for k, v in F.CATALOG.items() if k in F.COMBINATORS}
        lib = {k: {"args": v["params"], "meaning": v["doc"]} for k, v in F.STD_LIB.items()}
        return {"atoms": atoms, "combinators": comb, "library": lib,
                "units": "metres, degrees, m/s, seconds from the start of the task",
                "own_definitions": "allowed" if self.level >= 2 else "not allowed at this level (use the library)"}

    def t_submit_spec(self, a: dict) -> dict:
        """Check a task specification (data, never executed) against the map and store it if it is accepted."""
        doc = a.get("spec") if isinstance(a.get("spec"), dict) else a
        if not isinstance(doc, dict) or "tasks" not in doc:
            raise ToolArgError("the specification must be a JSON object with a 'tasks' list")
        self.spec_attempts += 1
        self.last_spec = doc
        r = check_document(doc, self.q, max(1, self.level))
        if r["ok"]:
            g = grounding.grounding_errors(self.prompt, self.q, r.get("zones", []))
            g += grounding.intent_errors(self.prompt, set(r.get("ops", [])), r.get("zones", []), self.model)
            if g:
                r["ok"], r["errors"] = False, r["errors"] + g
        fb = feedback_text(r)
        if r["ok"]:
            self.spec = doc
            self.spec_needs = r.get("needs", {})
            names = sorted(_world_names(doc))
            if names:
                fb += ("\nNEXT: submit the world script. Create these entities/signals that the specification names (exact names): "
                       + ", ".join(names) + ". Then `handles = scenario.apply_spec(SPEC)`.")
            else:
                fb += ("\nNEXT: the specification names no vehicle, walker, parked car or signal, so submit EXACTLY this script and nothing else:\n"
                       "```python\nfrom usg.dsl import *\nscenario = ScenarioBuilder(\"scenario\", MAP, scenario_type=\"custom\")\n"
                       "handles = scenario.apply_spec(SPEC)\n```")
        return {"accepted": r["ok"], "feedback": fb, "done": False, "tasks": r["tasks"]}

    def t_submit_script(self, a: dict) -> dict:
        """Run the script in the sandboxed child process, validate it, keep the result if accepted."""
        if not a.get("code"):
            raise ToolArgError("'code' is empty: put the whole script in a ```python block inside the tool tag")
        self.last_code = a["code"]
        if self.level >= 1 and self.spec is None:
            return {"accepted": False, "done": False,
                    "feedback": "REJECTED: submit the task specification first with submit_spec; the script only builds the world around it."}
        self.attempts += 1
        res = run_script(a["code"], self.map_path, "map.xodr", spec=self.spec if self.level >= 1 else None, level=max(1, self.level))
        if res.ok:
            centres = [(z["x"], z["y"]) if z["kind"] == "disc" else (z["cx"], z["cy"])
                       for tk in res.spec["tasks"] for z in F.zones_in(tk["goal"]) if z["kind"] in ("disc", "rect")]
            g = grounding.grounding_errors(self.prompt, self.q, centres)
            ops = {a["op"] for tk in res.spec["tasks"] for fm in [tk["goal"]] + list(tk["safety"]) for a in F.atoms_in(fm)}
            from .scenario_types import axes_of
            g += grounding.intent_errors(self.prompt, ops, centres, self.model, axes_of(res.spec, self.model))
            if g and not self._fallback_mode:
                return {"accepted": False, "done": False,
                        "feedback": "REJECTED: fix the errors below and submit again.\n" + "\n".join(f"[ERROR] request not honoured: {e}" for e in g)}
            gate = self._esmini_gate(res)
            if gate:
                return {"accepted": False, "done": False, "feedback": "REJECTED: fix the errors below and submit again.\n[ERROR] " + gate}
            self.result = {"xosc": res.xosc, "spec": res.spec, "script": a["code"], "issues": res.issues, "plan": self.plan,
                           "attempts": self.attempts, "spec_doc": self.spec, "spec_attempts": self.spec_attempts,
                           "level": self.level, "margins": getattr(res, "margins", None), "tier": "model"}
        return {"accepted": res.ok, "feedback": res.feedback(), "done": res.ok}

    def _esmini_gate(self, res) -> str:
        """'' if esmini is not configured or loads and runs the scenario; else the reason it does not."""
        if self.esmini is None:
            return ""
        path = self._tmp / "gate.xodr"
        xodr.export_xodr(self.model, path, virtual=[(v["signal"], v["crossing"]) for v in res.spec.get("virtual_signals", [])])
        r = esmini_mod.run(self.esmini, res.xosc, path)
        return "" if esmini_mod.ok(r) else "the exported file does not pass a standard player: " + esmini_mod.message(r)

    # ----------------------------------------------------------- deterministic safety nets (usg.assist)
    def assist_world(self) -> dict:
        """The model's specification was accepted but its world script keeps failing: write the world script from what the specification needs."""
        if self.spec is None or not assist_mod.safe_names(self.spec_needs):
            return {"accepted": False, "feedback": "no accepted specification to build a world around"}
        code = assist_mod.world_script(self.spec, self.spec_needs, self.q)
        if code is None:
            return {"accepted": False, "feedback": "the specification names a signal that the map does not have"}
        r = self.t_submit_script({"code": code})
        if r.get("accepted") and self.result is not None:
            self.result["tier"] = "assisted"
        return r

    def assist_fallback(self) -> dict:
        """The model produced nothing usable: submit the reference script of the most likely scenario type (valid, but it need not match the request)."""
        kind, code = assist_mod.fallback_script(self.prompt)
        saved_level, saved_spec = self.level, self.spec
        self.level, self.spec, self._fallback_mode = 0, None, True      # a reference script uses the task helpers, not a specification
        try:
            r = self.t_submit_script({"code": code})
        finally:
            self.level, self.spec, self._fallback_mode = saved_level, saved_spec, False
        if r.get("accepted") and self.result is not None:
            self.result["tier"], self.result["fallback_type"] = "fallback", kind
        return r

    # ----------------------------------------------------------- helpers for the app
    def suggest_types(self, prompt: str) -> list[str]:
        return classify(prompt)

    def final_package(self, name: str = "scenario") -> str:
        """Self-contained scenario package (JSON string): map + OpenSCENARIO + spec + script."""
        assert self.result is not None and self.model is not None
        pkg = {"format": "usg-scenario-package/1", "name": name,
               "map": self.model.to_dict(), "xosc": self.result["xosc"],
               "spec": self.result["spec"], "script": self.result["script"],
               "plan": self.result["plan"], "issues": self.result["issues"], "spec_doc": self.result.get("spec_doc")}
        return json.dumps(pkg)


def system_prompt(level: int = 0) -> str:
    lines = []
    for t in tool_specs(level):
        ex = (f'\n    Example: <tool name="{t["name"]}">{json.dumps(t["example"])}</tool>' if t["example"] is not None else "")
        lines.append(f"- {t['name']}: {t['doc']}{ex}")
    tools = "\n".join(lines)
    if level == 0:
        return prompt_text("system.md").replace("{{TOOLS}}", tools).replace("{{DSL}}", prompt_text("dsl_reference.md"))
    spec_ref = prompt_text("spec_reference.md")
    if level == 1:
        spec_ref = spec_ref.replace("(and, at level 2 only, `\"defs\": {...}` with your own definitions)", "(use the library definitions; own definitions are not available)")
        spec_ref = spec_ref[:spec_ref.index("Your own definition (level 2)")] + spec_ref[spec_ref.index("## Rules"):]
    return (prompt_text("system_spec.md").replace("{{TOOLS}}", tools).replace("{{SPEC}}", spec_ref)
            .replace("{{DSL}}", prompt_text("dsl_world.md")))
