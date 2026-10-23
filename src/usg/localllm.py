"""Start a local model from LM Studio's own files, no manual server setup.

LM Studio ("Bionic" in newer builds) keeps downloaded models under ``~/.lmstudio/models`` and ships llama.cpp
engines (CPU, Vulkan, CUDA) under ``~/.lmstudio/extensions/backends``. This module lists those models and launches
the bundled ``llama-server`` on an OpenAI-compatible port, so ``usg app`` can bring the model up by itself.

* AMD / Intel iGPU  -> the **Vulkan** engine (used by default)
* NVIDIA eGPU       -> the **CUDA** engine (``backend="cuda"``) or Vulkan
* anything else     -> CPU engine

Environment overrides: ``LMSTUDIO_HOME`` (default ``~/.lmstudio``), ``USG_LLAMA_SERVER`` (path to any llama-server).
"""
from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .llm import LLMError

PORT = 8089
BACKENDS = ("auto", "vulkan", "cuda", "cpu")


def lmstudio_home() -> Path:
    return Path(os.environ.get("LMSTUDIO_HOME", Path.home() / ".lmstudio"))


# ------------------------------------------------------------------ models
@dataclass(frozen=True)
class LocalModel:
    label: str          # "lmstudio-community/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf"
    path: Path
    size_mb: int

    @property
    def title(self) -> str:
        return f"{self.path.stem}  ·  {self.size_mb / 1024:.1f} GB  ·  {self.path.parent.parent.name}"

    @property
    def mmproj(self) -> Optional[Path]:
        """The vision projector LM Studio stores next to multimodal models (mmproj-*.gguf), if any."""
        found = sorted(self.path.parent.glob("mmproj*.gguf"))
        return found[0] if found else None


_SHARD = re.compile(r"-0*(\d+)-of-0*\d+\.gguf$", re.I)


def list_models(home: Optional[Path] = None) -> list[LocalModel]:
    """Every downloaded GGUF (vision projectors and non-first shards excluded)."""
    root = (home or lmstudio_home()) / "models"
    out: list[LocalModel] = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*.gguf")):
        if p.name.lower().startswith("mmproj"):
            continue
        m = _SHARD.search(p.name)
        if m and int(m.group(1)) != 1:
            continue
        out.append(LocalModel(label=p.relative_to(root).as_posix(), path=p, size_mb=int(p.stat().st_size / 2**20)))
    return out


def preferred(models: list[LocalModel], hint: Optional[str] = None) -> Optional[LocalModel]:
    """Pick by user hint (path or substring), else prefer a Qwen3.5 4B, then any Qwen, then the first."""
    if hint:
        h = hint.lower()
        for m in models:
            if h == str(m.path).lower() or h in m.label.lower():
                return m
        return None
    for key in ("qwen3.5-4b", "qwen3.5", "qwen2.5-coder", "qwen"):
        for m in models:
            if key in m.label.lower():
                return m
    return models[0] if models else None


# ------------------------------------------------------------------ engines
def engines(home: Optional[Path] = None) -> dict[str, Path]:
    """{kind: llama-server path} for kinds vulkan / cuda / cpu (newest engine version wins)."""
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    found: dict[str, Path] = {}
    override = os.environ.get("USG_LLAMA_SERVER")
    if override and Path(override).exists():
        found["vulkan"] = found["cpu"] = Path(override)
        return found
    base = (home or lmstudio_home()) / "extensions" / "backends"
    for d in sorted(base.glob("llama.cpp-*")) if base.exists() else []:
        p = d / exe
        if not p.exists():
            continue
        n = d.name.lower()
        kind = "vulkan" if "vulkan" in n else "cuda" if "cuda" in n else "cpu" if "avx" in n or "cpu" in n else None
        if kind:
            found[kind] = p            # sorted ascending, so a newer version overwrites an older one
    return found


def choose_engine(backend: str, avail: dict[str, Path]) -> tuple[str, Path]:
    if backend not in BACKENDS:
        raise LLMError(f"unknown backend '{backend}'")
    order = {"auto": ["vulkan", "cuda", "cpu"], "vulkan": ["vulkan"], "cuda": ["cuda"], "cpu": ["cpu"]}[backend]
    for k in order:
        if k in avail:
            return k, avail[k]
    raise LLMError(f"no '{backend}' llama.cpp engine found under {lmstudio_home() / 'extensions' / 'backends'} "
                   f"(available: {sorted(avail) or 'none'}). Set USG_LLAMA_SERVER to a llama-server binary.")


def _bind_to_parent(proc: subprocess.Popen):
    """Make the child die with this process, even if we are killed hard (closing the terminal, Task Manager).

    Windows: a Job Object with KILL_ON_JOB_CLOSE (the handle closes when we exit). Returns the handle to keep alive.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("a", "b", "c", "d", "e", "f")]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcess", ctypes.c_size_t), ("PeakJob", ctypes.c_size_t)]

        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        job = k.CreateJobObjectW(None, None)
        info = EXT()
        info.Basic.LimitFlags = 0x2000                       # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        k.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))
        return job
    except Exception:
        return None


def _command(exe: Path, args: list[str]) -> list[str]:
    return [sys.executable, str(exe), *args] if exe.suffix == ".py" else [str(exe), *args]


def devices(exe: Path) -> list[str]:
    """GPUs the engine can see, e.g. ['Vulkan0: AMD Radeon(TM) Graphics (16270 MiB, 15457 MiB free)']."""
    try:
        r = subprocess.run(_command(exe, ["--list-devices"]), capture_output=True, text=True, timeout=30, cwd=exe.parent)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln.strip() for ln in (r.stdout + r.stderr).splitlines() if re.match(r"\s*(Vulkan|CUDA|ROCm|Metal|SYCL)\d*:", ln)]


# ------------------------------------------------------------------ the server process
class LocalServer:
    """One llama-server child process, managed for the lifetime of the app."""

    def __init__(self, port: int = PORT):
        self.port = port
        self.proc: Optional[subprocess.Popen] = None
        self.model: Optional[LocalModel] = None
        self.kind = ""
        self.device = ""
        self.ctx = 0
        self.vision = False
        self._job = None                   # keeps the kill-on-exit job object alive
        self.state = "stopped"            # stopped | starting | running | error
        self.message = "Model not started."
        self._lock = threading.Lock()
        self._log = Path(tempfile.gettempdir()) / "usg_llama_server.log"
        atexit.register(self.stop)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                return json.loads(r.read().decode()).get("status") == "ok"
        except Exception:
            return False

    def running_for(self, model: LocalModel, backend: str, ctx: int, vision: bool = False) -> bool:
        return (self.state == "running" and self.proc is not None and self.proc.poll() is None and self.model == model
                and self.ctx == ctx and (backend == "auto" or self.kind == backend) and (self.vision or not vision))

    def start(self, model: LocalModel, backend: str = "auto", ctx: int = 12288, timeout: float = 240.0, vision: bool = False) -> str:
        """Start (or restart) the server for ``model``. Blocks until it answers /health. Returns a status line.

        ``vision=True`` also loads the model's vision projector (mmproj) so requests may contain images."""
        with self._lock:
            if self.running_for(model, backend, ctx, vision):
                return self.message
            if vision and model.mmproj is None:
                raise LLMError(f"{model.path.stem} has no vision projector (mmproj-*.gguf) next to it, so it cannot read images")
            self._stop_locked()
            if self._healthy():
                raise LLMError(f"port {self.port} is already answering: another (or a left-over) llama-server is running. "
                           "End 'llama-server.exe' in Task Manager, or use it as an external server.")
            kind, exe = choose_engine(backend, engines())
            devs = devices(exe) if kind != "cpu" else []
            self.state, self.model, self.kind, self.ctx = "starting", model, kind, ctx
            self.device = devs[0].split(" (")[0] if devs else ("CPU" if kind == "cpu" else kind)
            self.message = f"Loading {model.path.stem} on {self.device} ..."
            ngl = "0" if kind == "cpu" else "99"
            args = ["-m", str(model.path), "-c", str(ctx), "-ngl", ngl, "--host", "127.0.0.1", "--port", str(self.port), "--jinja"]
            if vision:
                args += ["--mmproj", str(model.mmproj)]
            self.vision = vision
            logf = open(self._log, "wb")
            flags = 0x08000000 if os.name == "nt" else 0         # CREATE_NO_WINDOW
            try:
                self.proc = subprocess.Popen(_command(exe, args), cwd=exe.parent, stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)
            except OSError as e:
                self.state, self.message = "error", f"could not start {exe}: {e}"
                raise LLMError(self.message) from None
            self._job = _bind_to_parent(self.proc)
            t0 = time.time()
            while time.time() - t0 < timeout:
                if self.proc.poll() is not None:
                    tail = self._tail()
                    self.state, self.message = "error", f"model server exited ({self.proc.returncode}): {tail}"
                    raise LLMError(self.message)
                if self._healthy():
                    self.state = "running"
                    self.message = (f"Running {model.path.stem} on {self.device} ({kind}) | context {ctx} | {self.base_url}"
                                    + (" | vision on" if vision else ""))
                    return self.message
                time.sleep(0.5)
            self._stop_locked()
            self.state, self.message = "error", f"model server did not become ready within {timeout:.0f}s: {self._tail()}"
            raise LLMError(self.message)

    def _tail(self, n: int = 400) -> str:
        try:
            return self._log.read_text(errors="ignore")[-n:].replace("\n", " ").strip()
        except OSError:
            return ""

    def _stop_locked(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if self.state != "error":
            self.state, self.message = "stopped", "Model stopped."

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()


SERVER = LocalServer()
