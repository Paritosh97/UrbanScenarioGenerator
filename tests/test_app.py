import gradio as gr
import pytest

from usg import app
from usg.scenario_types import ARCHETYPES


def test_interface_builds():
    assert isinstance(app.build_app(), gr.Blocks)


def test_sample_map_script_result_flow():
    tools, status, fig = app.load_sample(None)
    assert "Sample map" in status and fig is not None

    feedback, tools, md, rows, fig, files, vr, story = app.run_script(ARCHETYPES["dyn_nav"]["template"], tools)
    assert feedback.startswith("OK") and "dyn_nav" in md and rows and fig is not None
    names = {f.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for f in files}
    assert names == {"scenario.xosc", "map.xodr", "scene_map.json", "script.py", "spec.json", "package.usgscene.json"}
    assert "<OpenSCENARIO" in open([f for f in files if f.endswith(".xosc")][0], encoding="utf-8").read()
    # storyboard: the user's task event and the car that starts when the task starts
    assert any("VR task 1" in r[3] for r in story) and any("Car1" in r[1] and "starts" in r[2] for r in story)
    # the button opens the player in a NEW tab and points at a registered package
    assert 'target="_blank"' in vr and "/player/#/play?pkg=/packages/" in vr and "Open in WebVR" in vr


def test_rejected_script_gives_feedback_and_no_result():
    tools, *_ = app.load_sample(None)
    feedback, tools, md, rows, fig, files, vr, story = app.run_script("import os\n", tools)
    assert "not allowed" in feedback and rows == [] and files is None and vr == "" and story == []


def test_actions_need_a_map():
    with pytest.raises(gr.Error):
        app.run_script("scenario = 1", None)


def test_file_upload_loads_osm(tmp_path):
    from usg import synth
    p = tmp_path / "x.osm"
    p.write_text(synth.synthetic_osm(), encoding="utf-8")
    tools, status, fig = app.load_file(None, str(p))
    assert "x.osm" in status


# ------------------------------------------------------------------ the streaming Generate handler against a scripted model server
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def _scripted_server(replies):
    class H(BaseHTTPRequestHandler):
        n = 0

        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"data": [{"id": "qwen3.5:4b"}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            reply = replies[min(H.n, len(replies) - 1)]
            H.n += 1
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for i in range(0, len(reply), 40):
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': reply[i:i + 40]}}]})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_generate_streams_and_produces_a_result():
    code = ARCHETYPES["dyn_nav"]["template"]
    replies = ['<tool name="get_map_overview">{}</tool>',
               '<tool name="list_features">{"kind": "crossing", "control": "zebra"}</tool>',
               f'<tool name="submit_script">\n```python\n{code}\n```\n</tool>']
    srv = _scripted_server(replies)
    try:
        tools, *_ = app.load_sample(None)
        updates = list(app.generate("A car approaches", app.EXTERNAL, None, "auto", 12288, f"http://127.0.0.1:{srv.server_port}/v1", "qwen3.5:4b", 8, 0.2, tools,
                                    "L0 · script only (task helpers)"))
    finally:
        srv.shutdown()
    # Gradio rejects a yield whose length differs from the number of output components (10: log + 7 result outputs + 2 editors)
    assert {len(u) for u in updates} == {10}, [len(u) for u in updates]
    logs = [u[0] for u in updates]
    assert any("▶ get_map_overview" in l for l in logs) and "✅ scenario accepted" in logs[-1]
    log, state, md, rows, fig, files, vr, story, spec_text, code_text = updates[-1]
    assert state is tools and "dyn_nav" in md and rows and fig is not None and len(files) == 6 and "Open in WebVR" in vr


def test_generate_reports_model_server_down():
    tools, *_ = app.load_sample(None)
    updates = list(app.generate("x", app.EXTERNAL, None, "auto", 12288, "http://127.0.0.1:9/v1", "m", 4, 0.2, tools))
    assert "model error" in updates[-1][0] or "model error" in updates[-1][2]


# ------------------------------------------------------------------ one server: Gradio + player + packages
def test_server_serves_the_player_and_registered_packages_only():
    from fastapi.testclient import TestClient
    tools, *_ = app.load_sample(None)
    vr = app.run_script(ARCHETYPES["ptp_env"]["template"], tools)[6]                # the WebVR button html
    token = vr.split("/packages/")[1].split(".json")[0]
    client = TestClient(app.create_server(app.build_app()))
    r = client.get(f"/packages/{token}.json")
    assert r.status_code == 200 and r.json()["format"] == "usg-scenario-package/1" and "<OpenSCENARIO" in r.json()["xosc"]
    assert client.get("/packages/" + "0" * 32 + ".json").status_code == 404          # unknown token
    assert client.get("/packages/..%2f..%2fetc.json").status_code in (404, 422)       # no path tricks
    if app.PLAYER_DIR.exists():
        page = client.get("/player/")
        assert page.status_code == 200 and "Urban Scenario Player" in page.text
    assert client.get("/").status_code == 200                                         # Gradio at the root


def test_generate_output_width_matches_the_wired_components():
    """Catch handler/outputs drift: build the UI and compare each generate yield to its output list."""
    blocks = app.build_app()
    fn = next(f for f in blocks.fns.values() if getattr(f.fn, "__name__", "") == "generate")
    assert len(fn.outputs) == 10
    tools, *_ = app.load_sample(None)
    ups = list(app.generate("x", app.EXTERNAL, None, "auto", 12288, "http://127.0.0.1:9/v1", "m", 4, 0.2, tools))
    assert all(len(u) == len(fn.outputs) for u in ups)
