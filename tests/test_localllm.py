import json
import socket
import textwrap

import pytest

from usg import localllm
from usg.llm import LLMError

FAKE_ENGINE = textwrap.dedent('''
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    if "--list-devices" in sys.argv:
        print("Available devices:\\n  Vulkan0: Fake GPU (1000 MiB, 900 MiB free)")
        sys.exit(0)
    port = int(sys.argv[sys.argv.index("--port") + 1])
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    HTTPServer(("127.0.0.1", port), H).serve_forever()
''')


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / ".lmstudio"
    (h / "models" / "lmstudio-community" / "Qwen3.5-4B-GGUF").mkdir(parents=True)
    (h / "models" / "lmstudio-community" / "Qwen3.5-4B-GGUF" / "Qwen3.5-4B-Q4_K_M.gguf").write_bytes(b"x" * 2048)
    (h / "models" / "lmstudio-community" / "Qwen3.5-4B-GGUF" / "mmproj-Qwen3.5-4B-BF16.gguf").write_bytes(b"x" * 10)
    (h / "models" / "other" / "Big-GGUF").mkdir(parents=True)
    (h / "models" / "other" / "Big-GGUF" / "Big-Q4-00001-of-00002.gguf").write_bytes(b"x")
    (h / "models" / "other" / "Big-GGUF" / "Big-Q4-00002-of-00002.gguf").write_bytes(b"x")
    (h / "models" / "other" / "Llama-3-GGUF").mkdir(parents=True)
    (h / "models" / "other" / "Llama-3-GGUF" / "Llama-3-8B.gguf").write_bytes(b"x")
    for kind, ver in [("vulkan-avx2", "2.54.0"), ("vulkan-avx2", "2.55.0"), ("nvidia-cuda-avx2", "2.55.0"), ("avx2", "2.55.0")]:
        d = h / "extensions" / "backends" / f"llama.cpp-win-x86_64-{kind}-{ver}"
        d.mkdir(parents=True)
        (d / ("llama-server.exe" if __import__("os").name == "nt" else "llama-server")).write_bytes(b"")
    monkeypatch.setenv("LMSTUDIO_HOME", str(h))
    return h


def test_lists_downloaded_models_without_projectors_or_extra_shards(home):
    labels = [m.label for m in localllm.list_models()]
    assert labels == ["lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf", "other/Big-GGUF/Big-Q4-00001-of-00002.gguf",
                      "other/Llama-3-GGUF/Llama-3-8B.gguf"]


def test_preferred_model(home):
    ms = localllm.list_models()
    assert "Qwen3.5-4B" in localllm.preferred(ms).label
    assert localllm.preferred(ms, "llama-3").label.endswith("Llama-3-8B.gguf")
    assert localllm.preferred(ms, "does-not-exist") is None


def test_engine_discovery_picks_newest_per_kind(home):
    e = localllm.engines()
    assert set(e) == {"vulkan", "cuda", "cpu"} and "2.55.0" in str(e["vulkan"])
    assert localllm.choose_engine("auto", e)[0] == "vulkan"
    assert localllm.choose_engine("cuda", e)[0] == "cuda"
    with pytest.raises(LLMError, match="unknown backend"):
        localllm.choose_engine("tpu", e)
    with pytest.raises(LLMError, match="no 'cuda' llama.cpp engine"):
        localllm.choose_engine("cuda", {"vulkan": e["vulkan"]})


def test_no_lmstudio_means_no_models(tmp_path, monkeypatch):
    monkeypatch.setenv("LMSTUDIO_HOME", str(tmp_path / "nothing"))
    assert localllm.list_models() == [] and localllm.engines() == {}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_server_lifecycle_with_a_fake_engine(home, tmp_path, monkeypatch):
    eng = tmp_path / "fake_engine.py"
    eng.write_text(FAKE_ENGINE)
    monkeypatch.setenv("USG_LLAMA_SERVER", str(eng))
    model = localllm.list_models()[0]
    srv = localllm.LocalServer(port=_free_port())
    try:
        assert localllm.devices(eng) == ["Vulkan0: Fake GPU (1000 MiB, 900 MiB free)"]
        msg = srv.start(model, "auto", 8192, timeout=30)
        assert srv.state == "running" and "Fake GPU" in msg and "Qwen3.5-4B-Q4_K_M" in msg
        assert srv.running_for(model, "auto", 8192) and not srv.running_for(model, "auto", 4096)
        assert srv.start(model, "auto", 8192) == msg                       # no restart when nothing changed
        first_pid = srv.proc.pid
        srv.start(model, "auto", 4096, timeout=30)                          # new context size => restart
        assert srv.proc.pid != first_pid and srv.state == "running"
    finally:
        srv.stop()
    assert srv.state == "stopped" and not srv._healthy()


def test_server_reports_a_crashing_engine(home, tmp_path, monkeypatch):
    eng = tmp_path / "bad_engine.py"
    eng.write_text("import sys; print('boom: cannot load model'); sys.exit(3)")
    monkeypatch.setenv("USG_LLAMA_SERVER", str(eng))
    srv = localllm.LocalServer(port=_free_port())
    with pytest.raises(LLMError, match="exited .*boom"):
        srv.start(localllm.list_models()[0], "auto", 8192, timeout=30)
    assert srv.state == "error"


@pytest.mark.skipif(__import__("os").name != "nt", reason="job objects are Windows-only")
def test_engine_dies_with_the_app_even_on_a_hard_kill(home, tmp_path, monkeypatch):
    """A parent that is killed without running atexit (closing the terminal) must not leave llama-server behind."""
    import subprocess, sys, time
    eng = tmp_path / "fake_engine.py"
    eng.write_text(FAKE_ENGINE)
    port = _free_port()
    parent = tmp_path / "parent.py"
    parent.write_text(textwrap.dedent(f'''
        import os, sys
        from usg import localllm
        srv = localllm.LocalServer(port={port})
        srv.start(localllm.list_models()[0], "auto", 8192, timeout=30)
        print(srv.proc.pid, flush=True)
        os._exit(0)          # hard exit: no atexit, no cleanup
    '''))
    env = dict(__import__("os").environ, LMSTUDIO_HOME=str(home), USG_LLAMA_SERVER=str(eng))
    out = subprocess.run([sys.executable, str(parent)], capture_output=True, text=True, env=env, timeout=60)
    child = int(out.stdout.strip().splitlines()[-1])
    deadline = time.time() + 10
    alive = True
    while time.time() < deadline and alive:
        alive = str(child) in subprocess.run(["tasklist", "/FI", f"PID eq {child}"], capture_output=True, text=True).stdout
        time.sleep(0.3)
    assert not alive, "model server survived its parent"
