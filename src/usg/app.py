"""Gradio front end: pick a map, describe the task, let the local LLM agent write a validated scenario, then press
**Open in WebVR** to walk through it (VR headset if present, otherwise first person) in the bundled three.js player.

Run:  python -m usg.cli app
One server hosts everything: the Gradio UI at /, the player at /player/, and scenario packages at /packages/<token>.json.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import uuid
import webbrowser
from pathlib import Path
from typing import Optional

import gradio as gr
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import localllm, osm, storyboard, synth
from .agent.loop import run_agent
from .llm import LLMClient, LLMError, PRESETS
from .render import map_figure
from .scenario_types import ARCHETYPES, axes_label, axes_of
from .spec import formula as F
from .spec.document import document_from_spec
from .tools import ToolServer

EXAMPLES = {
    "ptp_env - walk to the bus stop": "Walk along the sidewalk to the bus stop.",
    "ptp_road - stand on the road": "Walk out onto the road and stand on the marked spot just past the crossing.",
    "cpath - stay on the path": "Cross the road but stay inside the marked corridor along the crosswalk.",
    "env_con - parked cars": "Cross the road at the zebra crossing without touching the parked cars.",
    "dyn_nav - approaching car": "Cross at the zebra crossing while a car approaches; avoid being hit.",
    "dep_comp - in order": "First walk to the crossing, then cross the road, then continue to the spot on the other side.",
    "indep_comp - any order": "Visit the waste basket and the street lamp, in any order.",
}
MAX_AREA_KM2 = 1.0
TASK_HEADERS = ["#", "type", "instruction", "after", "timeout s", "goal (specification)", "rules", "nominal margin"]
PIPELINES = {"L2 · specification + own definitions": 2, "L1 · specification from the library": 1, "L0 · script only (task helpers)": 0}
DEFAULT_PIPELINE = next(iter(PIPELINES))
PLAYER_DIR = Path(__file__).parent / "player_dist"          # built three.js player (see player/README in the repo)
PACKAGES: dict[str, Path] = {}                              # token -> scenario package file served at /packages/<token>.json
_TOKEN = re.compile(r"^[0-9a-f]{32}$")
SERVER_PORT = 7860
WEB_DIR = Path(__file__).parent / "web"
BBOX: dict = {}                                             # the area drawn in the map picker: {south, west, north, east}
DEFAULT_CTX = 16384                                         # the specification pipeline needs a long prompt


# ------------------------------------------------------------------ helpers
def _tools(t: Optional[ToolServer]) -> ToolServer:
    return t if t is not None else ToolServer()


def _need_map(t: Optional[ToolServer]) -> ToolServer:
    if t is None or t.model is None:
        raise gr.Error("Load a map first (tab 1).")
    return t


def _map_outputs(t: ToolServer, label: str):
    c = t.q.overview()["counts"]
    status = (f"**{label}**: {c['roads']} road segments, {c['junctions']} junctions, {c['crossings']} crossings, "
              f"{c['signals']} signals, {c['bus_stops']} bus stops, {c['buildings']} buildings")
    return t, status, map_figure(t.model)


def _result_files(t: ToolServer) -> tuple[list[str], str]:
    """Write the downloadable files, register the package for the player, return (paths, token)."""
    r = t.result
    d = t._tmp
    (d / "scenario.xosc").write_text(r["xosc"], encoding="utf-8")
    (d / "script.py").write_text(r["script"], encoding="utf-8")
    t.xodr_text()
    (d / "spec.json").write_text(json.dumps(r.get("spec_doc") or document_from_spec(r["spec"]), indent=1), encoding="utf-8")
    pkg = d / "package.usgscene.json"
    pkg.write_text(t.final_package(r["spec"]["name"]), encoding="utf-8")
    token = uuid.uuid4().hex
    PACKAGES[token] = pkg
    return [str(d / n) for n in ("scenario.xosc", "map.xodr", "scene_map.json", "script.py", "spec.json", "package.usgscene.json")], token


def vr_button_html(token: str, port: int = SERVER_PORT) -> str:
    """The 'Open in WebVR' button (opens the player in a new tab) plus headset instructions."""
    if not PLAYER_DIR.exists():
        return ("<p style='color:#ff6b6b'>The player is not built. Run <code>cd player && npm install && npm run build</code> "
                "once, then restart the app.</p>")
    path = f"/player/#/play?pkg=/packages/{token}.json"
    return f"""
<div style="padding:14px;border:1px solid #2a3542;border-radius:10px;background:#12181f">
  <a href="{path}" target="_blank" rel="noopener"
     style="display:inline-block;background:#35e0ff;color:#04222a;font-weight:700;padding:10px 20px;border-radius:8px;text-decoration:none;font-size:16px">
     Open in WebVR &#8599;</a>
  <span style="margin-left:14px;opacity:.85">Opens a new tab. With a VR headset it offers <b>Enter VR</b>; without one it runs in
  first person (<b>WASD</b> + mouse). You are the pedestrian: the guided tasks, signals and traffic are all live.</span>
  <details style="margin-top:10px;opacity:.9"><summary>Using a headset?</summary>
    <ul style="margin:6px 0 0 18px;line-height:1.6">
      <li><b>Tethered</b> (Quest Link / Air Link / SteamVR): press the button in Chrome or Edge on this PC.</li>
      <li><b>Standalone Quest</b> (USB cable, developer mode): run <code>python -m usg.cli adb-reverse</code> once, then open
        <code>http://localhost:{port}{path}</code> in the headset's browser. (WebXR only works on HTTPS or localhost, which is why a plain
        LAN address will not offer VR.)</li>
    </ul></details>
</div>"""


def _result_panel(t: ToolServer):
    """(summary markdown, task table, scenario figure, downloads, WebVR button html, storyboard rows)"""
    r = t.result
    if not r:
        return "_No accepted scenario yet._", [], None, None, "", []
    spec = r["spec"]
    notes = "\n".join(f"- {i['severity']}: {i['message']}" for i in r["issues"])
    md = (f"### {spec['name']} · `{spec.get('scenario_type')}`\n{spec.get('description') or ''}\n\n"
          f"Constraint axes: {axes_label(axes_of(spec, t.model))}\n\n"
          f"Accepted after {r['attempts']} script submission(s)." + (f"\n\nValidator notes:\n{notes}" if notes else ""))
    rows = []
    margins = r.get("margins") or {}
    for tk in spec["tasks"]:
        rules = "; ".join(x.get("label") or F.describe(x) for x in tk["safety"]) or "-"
        mg = margins.get(str(tk["id"]))
        nominal = "-" if not mg else f"goal {mg['goal']:+.2f}" + (f", rules {mg['min_safety']:+.2f}" if mg["min_safety"] is not None else "")
        rows.append([tk["id"], tk["category"], tk["instruction"].get("en", ""), ",".join(map(str, tk["depends_on"])) or "-",
                     tk["timeout"]["initial"], F.describe(tk["goal"])[:110], rules[:110], nominal])
    files, token = _result_files(t)
    return md, rows, map_figure(t.model, spec), files, vr_button_html(token), storyboard.storyboard_rows(r["xosc"])


# ------------------------------------------------------------------ map tab
def load_sample(t):
    t = _tools(t)
    t.load_osm(synth.synthetic_osm())
    return _map_outputs(t, "Sample map")


def bbox_text() -> str:
    """Markdown line describing the area currently drawn in the map picker."""
    if not BBOX:
        return "No area selected yet: search for a place above, then **Draw area** (or **Use current view**)."
    b = _bbox_tuple()
    km2 = osm.bbox_area_km2(b)
    flag = "✅" if km2 <= MAX_AREA_KM2 else f"❌ too large (at most {MAX_AREA_KM2} km²)"
    return f"{flag} **Selected area:** {km2:.3f} km² · S {b[0]:.5f}, W {b[1]:.5f}, N {b[2]:.5f}, E {b[3]:.5f}"


def _bbox_tuple() -> tuple[float, float, float, float]:
    return (BBOX["south"], BBOX["west"], BBOX["north"], BBOX["east"])


def poll_bbox() -> str:
    return bbox_text()


def load_selected(t):
    """Download the OpenStreetMap data for the rectangle drawn in the picker and build the map."""
    t = _tools(t)
    if not BBOX:
        raise gr.Error("Draw an area on the map first (search, then 'Draw area').")
    b = _bbox_tuple()
    if osm.bbox_area_km2(b) > MAX_AREA_KM2:
        raise gr.Error(f"The area is {osm.bbox_area_km2(b):.2f} km2; choose at most {MAX_AREA_KM2} km2 (draw a smaller rectangle).")
    try:
        path = osm.fetch_osm(*b)
    except Exception as e:                                           # network/Overpass problems
        raise gr.Error(f"Could not download OpenStreetMap data: {e}") from None
    t.load_osm(Path(path).read_text(encoding="utf-8"), list(b))
    return _map_outputs(t, f"Map of the selected area ({osm.bbox_area_km2(b):.2f} km²)")


def load_file(t, f):
    if f is None:
        raise gr.Error("Choose an .osm file first.")
    t = _tools(t)
    t.load_osm(Path(f).read_text(encoding="utf-8"))
    return _map_outputs(t, Path(f).name)


# ------------------------------------------------------------------ model connection
def refresh_models(url, current):
    try:
        models = LLMClient(base_url=url).list_models()
    except LLMError as e:
        return gr.update(choices=[], value=current), f"❌ {e}"
    if not models:
        return gr.update(choices=[], value=current), "Connected, but the server lists no models. Pull/load one first."
    pick = current if current in models else next((m for m in models if "qwen3.5" in m.lower()), None) or \
        next((m for m in models if "qwen" in m.lower()), models[0])
    return gr.update(choices=models, value=pick), f"✅ Connected - {len(models)} model(s) available."


# ------------------------------------------------------------------ local model (LM Studio files + bundled llama.cpp)
LOCAL, EXTERNAL = "Local model (LM Studio files)", "External server (Ollama / LM Studio server / llama.cpp)"


def _local_choices() -> list[tuple[str, str]]:
    return [(m.title, str(m.path)) for m in localllm.list_models()]


def _find_local(path: Optional[str]) -> localllm.LocalModel:
    for m in localllm.list_models():
        if str(m.path) == path:
            return m
    raise gr.Error("Pick a downloaded model in the dropdown (tab 2).")


def start_local(path, backend, ctx):
    """Button handler: load the chosen model on the GPU. Returns the status line."""
    m = _find_local(path)
    try:
        return "✅ " + localllm.SERVER.start(m, backend, int(ctx))
    except LLMError as e:
        return f"❌ {e}"


def stop_local():
    localllm.SERVER.stop()
    return "Model stopped."


def local_status():
    s = localllm.SERVER
    icon = {"running": "✅", "starting": "⏳", "error": "❌", "stopped": "⏹"}[s.state]
    return f"{icon} {s.message}"


def refresh_local():
    ch = _local_choices()
    return gr.update(choices=ch, value=(ch[0][1] if ch else None)), f"{len(ch)} downloaded model(s) found in {localllm.lmstudio_home() / 'models'}"


# ------------------------------------------------------------------ generation
def generate(prompt, source, local_path, backend, ctx, url, model, max_steps, temperature, t, pipeline=DEFAULT_PIPELINE, vision=False):
    t = _need_map(t)
    if not (prompt or "").strip():
        raise gr.Error("Describe the task first.")
    t.result = None
    t.attempts = t.spec_attempts = 0
    t.spec = None
    t.level = PIPELINES.get(pipeline, 2)
    t.vision = bool(vision)
    skip7 = tuple(gr.skip() for _ in range(9))                     # leave state/result panels and editors untouched while streaming
    if source == LOCAL:
        lm = _find_local(local_path)
        if vision and lm.mmproj is None:
            raise gr.Error(f"{lm.path.stem} has no vision projector (mmproj-*.gguf) next to it; untick 'map image'.")
        if not localllm.SERVER.running_for(lm, backend, int(ctx), bool(vision)):
            yield (f"⏳ loading {lm.path.stem} on the GPU …", *skip7)
            try:
                localllm.SERVER.start(lm, backend, int(ctx), vision=bool(vision))
            except LLMError as e:
                raise gr.Error(str(e)) from None
        llm = LLMClient(base_url=localllm.SERVER.base_url, model="local", temperature=float(temperature), context_tokens=int(ctx))
    else:
        if not model:
            raise gr.Error("Pick a model (tab 2, 'Refresh models').")
        llm = LLMClient(base_url=url, model=model, temperature=float(temperature))
    q: queue.Queue = queue.Queue()
    stop = threading.Event()

    class Stopped(Exception):
        pass

    def on_token(tok: str) -> None:
        if stop.is_set():
            raise Stopped()
        q.put(("token", tok))

    def worker() -> None:
        try:
            for ev in run_agent(llm, t, prompt, int(max_steps), on_token=on_token):
                q.put(("event", ev))
        except Stopped:
            q.put(("event", {"kind": "failed", "reason": "stopped"}))
        except LLMError as e:
            q.put(("event", {"kind": "failed", "reason": f"model error: {e}"}))
        except Exception as e:                                       # surface anything unexpected in the log
            q.put(("event", {"kind": "failed", "reason": f"{type(e).__name__}: {e}"}))
        q.put(("end", None))

    threading.Thread(target=worker, daemon=True).start()
    lines: list[str] = []
    live = ""
    final: Optional[dict] = None
    try:
        while True:
            try:
                kind, val = q.get(timeout=0.4)
            except queue.Empty:
                yield ("\n".join(lines + ([f"   … {live[-160:]}"] if live else [])), *skip7)
                continue
            if kind == "token":
                live += val
                if len(live) % 12 == 0:
                    yield ("\n".join(lines + [f"   … {live[-160:]}"]), *skip7)
                continue
            if kind == "end":
                break
            ev = val
            live = ""
            k = ev["kind"]
            if k == "thinking":
                lines.append(f"💭 {ev['text']}")
            elif k == "tool":
                lines.append(f"▶ {ev['name']} {json.dumps(ev['args'])[:140]}")
            elif k == "result":
                lines.append(f"   {'✓' if ev['ok'] else '✗'} {ev['summary']}")
            elif k == "warning":
                lines.append(f"⚠ {ev['text']}")
            elif k in ("done", "failed"):
                final = ev
                lines.append("✅ scenario accepted" if k == "done" else f"❌ stopped: {ev.get('reason')}")
            yield ("\n".join(lines), *skip7)
    finally:
        stop.set()
    if final and final["kind"] == "done":
        panel = _result_panel(t)
        spec_text = json.dumps(t.result.get("spec_doc") or document_from_spec(t.result["spec"]), indent=1)
        code_text = t.result["script"]
    else:
        panel = (f"**No scenario produced** ({final.get('reason') if final else 'unknown'}). "
                 "The last attempt is in the editors below: fix it and press *Validate & build my edits*.", [], None, None, "", [])
        spec_text = json.dumps(t.last_spec, indent=1) if t.last_spec else gr.skip()
        code_text = t.last_code if t.last_code else gr.skip()
    yield ("\n".join(lines), t, *panel, spec_text, code_text)


# ------------------------------------------------------------------ scripts tab
def load_template(sid):
    return ARCHETYPES[sid]["template"] if sid else ""


def run_script(code, t, spec_json=None):
    t = _need_map(t)
    t.result = None
    t.prompt = ""                                                   # manual edits are not checked against an earlier request
    feedback = ""
    if (spec_json or "").strip():                                   # a hand-written specification: checked like the agent's
        try:
            doc = json.loads(spec_json)
        except ValueError as e:
            raise gr.Error(f"The specification is not valid JSON: {e}") from None
        t.level = 2
        r = t.call("submit_spec", doc)
        feedback = "SPECIFICATION\n" + r.get("feedback", r.get("error", "")) + "\n\nSCRIPT\n"
        if not r.get("accepted"):
            return (feedback + "(not run: fix the specification first)", t, *_result_panel(t))
    else:
        t.level, t.spec = 0, None
    res = t.call("submit_script", {"code": code})
    return (feedback + res.get("feedback", ""), t, *_result_panel(t))


# ------------------------------------------------------------------ layout
def build_app(default_model: Optional[str] = None, default_backend: str = "auto", default_ctx: int = DEFAULT_CTX) -> gr.Blocks:
    with gr.Blocks(title="Urban Scenario Generator") as app:
        gr.Markdown("# Urban Scenario Generator\nPedestrian guided-task scenarios from OpenStreetMap + a prompt, "
                    "planned by a local LLM, validated against the map, and playable in WebVR.")
        tools = gr.State(None)

        with gr.Tabs():
            with gr.Tab("1 · Map"):
                gr.Markdown("**Search** for a place, zoom to the street you want, then press **Draw area** and drag a rectangle "
                            f"(at most {MAX_AREA_KM2:g} km²). Or press **Use current view**.")
                gr.HTML('<iframe src="/mapselect/" title="Select an area" style="width:100%;height:540px;border:1px solid #2b3947;'
                        'border-radius:8px;background:#10161c"></iframe>')
                bbox_md = gr.Markdown(bbox_text())
                with gr.Row():
                    b_load = gr.Button("Load map of the selected area", variant="primary")
                    b_sample = gr.Button("Use the sample city instead")
                    f_osm = gr.File(label="…or an .osm file", file_types=[".osm", ".xml"], type="filepath")
                map_status = gr.Markdown("Load a map to begin.")
                map_plot = gr.Plot(label="Map")
                bbox_timer = gr.Timer(1.5)

            with gr.Tab("2 · Generate"):
                example = gr.Dropdown(list(EXAMPLES), label="Example prompts", value=None)
                prompt = gr.Textbox(label="What should the pedestrian do?", lines=3, value=EXAMPLES["dyn_nav - approaching car"])
                choices = _local_choices()
                chosen = localllm.preferred(localllm.list_models(), default_model)
                with gr.Row():
                    local_model = gr.Dropdown(choices, value=str(chosen.path) if chosen else None, label="Local model (LM Studio files)", scale=3)
                    b_start = gr.Button("Restart model", scale=1)
                    b_unload = gr.Button("Stop model", scale=1)
                local_md = gr.Markdown(local_status() if choices else
                                       f"No downloaded model found under {localllm.lmstudio_home() / 'models'}. Download one in LM Studio first.")
                with gr.Accordion("Advanced", open=False):
                    vision = gr.Checkbox(False, label="Give the model an annotated top-down map image (needs the vision projector file next to the GGUF)")
                    with gr.Row():
                        steps = gr.Slider(8, 30, 22, step=1, label="Max agent steps")
                        temp = gr.Slider(0, 1, 0.2, step=0.05, label="Temperature")
                with gr.Row():
                    b_gen = gr.Button("Generate scenario", variant="primary")
                    b_stop = gr.Button("Stop")
                log = gr.Textbox(label="Agent log", lines=12, max_lines=12, autoscroll=True, interactive=False)

                gr.Markdown("### Generated scenario (editable)\nThe **specification** says what the participant must do (goal + rules); the **world script** builds "
                            "the street scene around it (vehicles, signals) and ends with `scenario.apply_spec(SPEC)`. Change either one and press "
                            "**Validate & build my edits**.")
                with gr.Row():
                    spec_box = gr.Code(language="json", label="Task specification (JSON)", lines=18, interactive=True)
                    code_box = gr.Code(language="python", label="World script (Python)", lines=18, interactive=True)
                with gr.Row():
                    b_run = gr.Button("Validate & build my edits", variant="primary")
                run_fb = gr.Textbox(label="Validator feedback", lines=6, interactive=False)

        gr.Markdown("---\n## Result")
        res_md = gr.Markdown("_No accepted scenario yet._")
        res_vr = gr.HTML()
        with gr.Row():
            res_fig = gr.Plot(label="Scenario overlay (green = your start, red dashed = vehicle routes, cyan rings = targets)")
            res_tasks = gr.Dataframe(headers=TASK_HEADERS, interactive=False, wrap=True, label="Guided tasks")
        res_story = gr.Dataframe(headers=storyboard.HEADERS, interactive=False, wrap=True, label="OpenSCENARIO storyboard (what runs, and when)")
        res_files = gr.File(label="Downloads (OpenSCENARIO, OpenDRIVE, map JSON, script, specification, package)", file_count="multiple")

        # constants the generate handler still takes as inputs (the interface has no controls for them any more)
        k_source, k_backend, k_ctx = gr.State(LOCAL), gr.State(default_backend), gr.State(default_ctx)
        k_url, k_model, k_pipe = gr.State(""), gr.State(""), gr.State(DEFAULT_PIPELINE)

        # ---- wiring
        map_outs = [tools, map_status, map_plot]
        b_load.click(load_selected, [tools], map_outs)
        b_sample.click(load_sample, [tools], map_outs)
        f_osm.upload(load_file, [tools, f_osm], map_outs)
        bbox_timer.tick(poll_bbox, None, [bbox_md])
        example.change(lambda k: EXAMPLES.get(k, gr.skip()), [example], [prompt])
        b_start.click(lambda: "⏳ loading the model on the GPU …", None, [local_md]).then(start_local, [local_model, k_backend, k_ctx], [local_md])
        b_unload.click(stop_local, None, [local_md])
        ticker = gr.Timer(2.0)
        ticker.tick(local_status, None, [local_md])
        app.load(local_status, None, [local_md])
        result_outs = [tools, res_md, res_tasks, res_fig, res_files, res_vr, res_story]
        gen = b_gen.click(generate, [prompt, k_source, local_model, k_backend, k_ctx, k_url, k_model, steps, temp, tools, k_pipe, vision],
                          [log, *result_outs, spec_box, code_box])
        b_stop.click(None, None, None, cancels=[gen])
        b_run.click(run_script, [code_box, tools, spec_box], [run_fb, *result_outs])
    return app


# ------------------------------------------------------------------ one server for Gradio + the player
def create_server(blocks: gr.Blocks) -> FastAPI:
    """FastAPI app: /player (static three.js player), /packages/<token>.json (generated scenarios), / (Gradio)."""
    api = FastAPI(title="usg")

    @api.get("/packages/{token}.json")
    def package(token: str):
        path = PACKAGES.get(token) if _TOKEN.match(token) else None
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="unknown scenario package")
        return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-store"})

    @api.get("/mapselect/")
    def mapselect():
        return HTMLResponse((WEB_DIR / "mapselect.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    @api.get("/api/bbox")
    def get_bbox():
        return dict(BBOX)

    @api.post("/api/bbox")
    def set_bbox(b: dict = Body(...)):
        try:
            v = {k: float(b[k]) for k in ("south", "west", "north", "east")}
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=422, detail="expected numbers south, west, north, east") from None
        if not (-90 <= v["south"] < v["north"] <= 90 and -180 <= v["west"] < v["east"] <= 180):
            raise HTTPException(status_code=422, detail="not a valid bounding box")
        BBOX.clear()
        BBOX.update(v)
        return {"ok": True, "area_km2": round(osm.bbox_area_km2(_bbox_tuple()), 4)}

    @api.delete("/api/bbox")
    def clear_bbox():
        BBOX.clear()
        return {"ok": True}

    if PLAYER_DIR.exists():
        api.mount("/player", StaticFiles(directory=str(PLAYER_DIR), html=True), name="player")
    return gr.mount_gradio_app(api, blocks.queue(), path="/")


def main(host: str = "127.0.0.1", port: int = 7860, inbrowser: bool = True, model: Optional[str] = None,
         backend: str = "auto", ctx: int = DEFAULT_CTX, autostart: bool = True) -> None:
    """Launch the interface; when LM Studio models exist, also start the chosen one in the background."""
    global SERVER_PORT
    import uvicorn
    SERVER_PORT = port
    models = localllm.list_models()
    chosen = localllm.preferred(models, model)
    if model and not chosen:
        print(f"[usg] no downloaded model matches '{model}'. Found: {[m.label for m in models]}")
    if autostart and chosen:
        def boot() -> None:
            try:
                print(f"[usg] starting {chosen.path.stem} ({backend}) ...", flush=True)
                print("[usg] " + localllm.SERVER.start(chosen, backend, ctx), flush=True)
            except LLMError as e:
                print(f"[usg] model did not start: {e}", flush=True)
        threading.Thread(target=boot, daemon=True).start()
    elif not models:
        print(f"[usg] no LM Studio models found under {localllm.lmstudio_home() / 'models'}; download a model in LM Studio first.")
    if not PLAYER_DIR.exists():
        print("[usg] the WebVR player is not built (cd player && npm install && npm run build); everything else works.")
    app = create_server(build_app(str(chosen.path) if chosen else None, backend, ctx))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/"
    print(f"[usg] open {url}", flush=True)
    if inbrowser:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
