import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from usg import synth
from usg.agent.loop import compact, parse_tool_call, run_agent, strip_thinking
from usg.llm import LLMClient, LLMError
from usg.scenario_types import ARCHETYPES
from usg.tools import ToolServer


class Scripted:
    """A model that replays canned replies and records what it was shown."""
    context_tokens = 16000

    def __init__(self, replies):
        self.replies, self.i, self.seen = replies, 0, []

    def chat(self, messages, max_tokens=1800, on_token=None):
        self.seen.append([dict(m) for m in messages])
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        if on_token:
            on_token(r)
        return r


def call(name, args):
    return f'<tool name="{name}">{json.dumps(args)}</tool>'


def submit(code):
    return f'Submitting.\n<tool name="submit_script">\n```python\n{code}\n```\n</tool>'


@pytest.fixture()
def tools():
    t = ToolServer()
    t.load_osm(synth.synthetic_osm())
    return t


# ------------------------------------------------------------------ parsing
def test_parse_json_args():
    c = parse_tool_call('thinking...\n<tool name="list_features">{"kind":"crossing","limit":3}</tool>')
    assert c.name == "list_features" and c.args == {"kind": "crossing", "limit": 3}


def test_parse_is_tolerant():
    assert parse_tool_call("<tool name=\"check_point\">{'x': 1, 'y': 2,}").args == {"x": 1, "y": 2}


def test_parse_fenced_script():
    c = parse_tool_call('<tool name="submit_script">\n```python\nfrom usg.dsl import *\nscenario = 1\n```\n</tool>')
    assert c.name == "submit_script" and c.args["code"].startswith("from usg.dsl")


def test_bare_scenario_block_counts_as_submission():
    assert parse_tool_call('Here:\n```python\nscenario = ScenarioBuilder("x", MAP)\n```').name == "submit_script"


def test_plain_text_is_not_a_call():
    assert parse_tool_call("I think we should cross.") is None


def test_reasoning_blocks_are_ignored():
    c = parse_tool_call('<think>maybe <tool name="check_point">{}</tool></think><tool name="get_map_overview">{}</tool>')
    assert c.name == "get_map_overview"
    assert strip_thinking("<think>x</think>ok") == "ok"


def test_compact_truncates_old_tool_results_first():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "req"}]
    for _ in range(8):
        msgs += [{"role": "assistant", "content": "a"}, {"role": "user", "content": "Tool result (x):\n" + "z" * 4000}]
    out = compact(msgs, 3000)
    assert len(out[3]["content"]) < 250 and len(out[-1]["content"]) > 3000


# ------------------------------------------------------------------ the loop
def test_agent_explores_gets_rejected_repairs_and_finishes(tools):
    good = ARCHETYPES["dyn_nav"]["template"]
    llm = Scripted([call("get_map_overview", {}), call("list_features", {"kind": "crossing", "control": "zebra"}),
                    call("record_plan", {"plan": {"type": "dyn_nav"}}), submit(good.replace("speed=8.0", "speed=0.0")), submit(good)])
    events = list(run_agent(llm, tools, "A car approaches while I cross the zebra crossing"))
    assert events[-1]["kind"] == "done" and events[-1]["steps"] == 5
    assert any(e["kind"] == "result" and not e["ok"] and "vehicle_speed" in e["summary"] for e in events)
    assert "vehicle_speed" in " ".join(m["content"] for m in llm.seen[4])          # model was told why it failed
    pkg = json.loads(tools.final_package("t"))
    assert pkg["spec"]["scenario_type"] == "dyn_nav" and "<OpenSCENARIO" in pkg["xosc"]


def test_agent_gives_up_on_a_model_that_never_calls_tools(tools):
    events = list(run_agent(Scripted(["I will think about it."]), tools, "x", max_steps=12))
    assert events[-1] == {"kind": "failed", "steps": 5, "reason": "model stopped calling tools"}


def test_agent_survives_unknown_tools_and_bad_ids(tools):
    llm = Scripted([call("nope", {}), call("get_feature", {"id": "zzz"}), submit(ARCHETYPES["ptp_env"]["template"])])
    assert list(run_agent(llm, tools, "x"))[-1]["kind"] == "done"


def test_agent_stops_after_repeated_rejections(tools):
    events = list(run_agent(Scripted([submit("scenario = 1")]), tools, "x", max_steps=20))
    assert events[-1]["kind"] == "failed" and "rejected" in events[-1]["reason"]


# ------------------------------------------------------------------ LLM client against a fake OpenAI server
class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "qwen3.5:4b"}, {"id": "llama3"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        req = json.loads(self.rfile.read(n))
        FakeHandler.last = req
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        for tok in ["Let me ", "look.\n<tool name=\"get_map_overview\">", "{}", "</tool>", " this must not be read"]:
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': tok}}]})}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


@pytest.fixture()
def server():
    s = HTTPServer(("127.0.0.1", 0), FakeHandler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}/v1"
    s.shutdown()


def test_client_lists_models_and_streams_until_tool_closes(server):
    c = LLMClient(base_url=server, model="qwen3.5:4b")
    assert c.list_models() == ["llama3", "qwen3.5:4b"]
    toks = []
    out = c.chat([{"role": "user", "content": "hi"}], on_token=toks.append)
    assert out.endswith("</tool>") and "must not be read" not in out
    assert FakeHandler.last["stream"] is True and FakeHandler.last["chat_template_kwargs"] == {"enable_thinking": False}
    assert parse_tool_call(out).name == "get_map_overview"


def test_client_reports_unreachable_server():
    with pytest.raises(LLMError, match="cannot reach"):
        LLMClient(base_url="http://127.0.0.1:9/v1").list_models()
