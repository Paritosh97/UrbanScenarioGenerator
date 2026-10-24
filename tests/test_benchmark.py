"""Benchmark harness pieces that need no model: the bare-template condition, remote-endpoint request bodies, multi-model summaries."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from usg.llm import LLMClient
from usg.scenario_types import ARCHETYPES

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bench():
    return _load("benchmark")


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat(self, messages, max_tokens=1800, on_token=None):
        self.calls.append(messages)
        return self.reply


ENTRY = {"id": "t1", "type": "ptp_env", "map": "synthetic", "text": "Walk to the bus stop.", "expect": {"axes": {"surface": "walkable"}}}


def test_template_condition_makes_one_call_and_validates_once(bench):
    llm = FakeLLM("Sure!\n```python\n" + ARCHETYPES["ptp_env"]["template"] + "\n```")
    rec = bench.run_template(llm, ENTRY)
    assert len(llm.calls) == 1 and rec["level"] == "T0" and rec["steps"] == 1
    assert rec["accepted"] and rec["first_try"] and rec["attempts"] == 1
    assert "Request: Walk to the bus stop." in llm.calls[0][0]["content"]


def test_template_condition_keeps_a_rejected_script(bench):
    rec = bench.run_template(FakeLLM("```python\nscenario = 1\n```"), ENTRY)
    assert not rec["accepted"] and rec["last_code"] == "scenario = 1" and not rec["first_try"]


def test_template_condition_reports_an_empty_reply(bench):
    rec = bench.run_template(FakeLLM(""), ENTRY)
    assert not rec["accepted"] and rec["reason"] == "empty reply"


def test_hosted_endpoints_get_a_plain_request_body():
    msgs = [{"role": "user", "content": "hi"}]
    local = LLMClient(model="m")._body(msgs, 100)
    hosted = LLMClient(model="m", local_extras=False)._body(msgs, 100)
    assert "chat_template_kwargs" in local and "think" in local
    assert set(hosted) == {"model", "messages", "stream", "temperature", "max_tokens"}


def test_summary_handles_the_template_condition_and_several_models(tmp_path):
    summ = _load("summarize_benchmark")
    base = {"type": "ptp_env", "map": "m1", "accepted": True, "first_try": True, "adherent": True, "recall": 1.0, "nominal_ok": True,
            "steps": 1, "seconds": 1.0, "attempts": 1, "spec_attempts": 0}
    rows = []
    for model in ("Qwen 4B", "api:claude"):
        for lv in ("T0", 0, 1, 2):
            for pid in ("a", "b"):
                rows.append({**base, "id": pid, "level": lv, "model": model, "rep": 0, "adherent": lv != "T0"})
    src = tmp_path / "b.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    summ.main(str(src), str(tmp_path / "out"))
    text = (tmp_path / "out" / "summary.md").read_text()
    assert "T0 bare prompt template" in text and "Model: api:claude" in text and "Model: Qwen 4B" in text
