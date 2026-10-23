"""Safe execution of LLM-written scenario scripts.

Layers (defence in depth - this is NOT a perfect jail, see docs/SECURITY.md):

1. **Static policy** (AST): only whitelisted imports, no dunder/underscore attribute access,
   no ``eval/exec/open/getattr/...``, no classes, no ``str.format`` (format-string escapes).
2. **Restricted runtime**: tiny builtins table, ``print`` is a no-op, an ``__import__`` that only
   hands out the whitelisted modules. The script cannot name ``os``/``sys``/``subprocess``.
3. **Process isolation**: runs in a child interpreter with a scrubbed environment, a temp
   working directory, wall-clock timeout and a memory cap (Windows Job Object /
   POSIX ``RLIMIT_AS``). The script never writes files: the host serialises the result.
4. **Validation**: a script is only accepted if the map-aware validator passes.

For multi-tenant/untrusted use, additionally run the whole thing in a container or WSL VM.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MAX_CODE = 30_000
ALLOWED_IMPORTS = {"usg.dsl", "usg", "math", "typing", "scenariogeneration", "scenariogeneration.xosc"}
DENY_NAMES = {"eval", "exec", "compile", "open", "__import__", "getattr", "setattr", "delattr", "globals",
              "locals", "vars", "dir", "input", "breakpoint", "help", "memoryview", "type", "object",
              "super", "classmethod", "staticmethod", "property", "exit", "quit", "os", "sys",
              "subprocess", "importlib", "builtins", "ctypes", "socket", "shutil", "pathlib", "inspect"}
DENY_ATTRS = {"format", "format_map", "write_xml", "write", "writelines", "read", "readlines", "open",
              "system", "popen", "remove", "unlink", "rmdir", "mkdir", "makedirs", "rename", "dump",
              "dumps", "load", "loads", "save", "exec", "eval", "mro", "ScenarioGenerator", "ElementTree",
              "to_xml_string", "to_xml", "write_text", "write_bytes", "read_text", "read_bytes"}
SAFE_BUILTINS = ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "isinstance",
                 "len", "list", "map", "max", "min", "range", "reversed", "round", "set", "sorted", "str",
                 "sum", "tuple", "zip", "ValueError", "TypeError", "KeyError", "IndexError", "Exception",
                 "StopIteration", "ZeroDivisionError")


class PolicyError(Exception):
    pass


def check_policy(code: str) -> None:
    """Raise PolicyError (with a message the LLM can act on) if the script breaks the static policy."""
    if len(code) > MAX_CODE:
        raise PolicyError(f"script too long ({len(code)} > {MAX_CODE} chars)")
    try:
        tree = ast.parse(code, "<scenario>")
    except SyntaxError as e:
        raise PolicyError(f"SyntaxError line {e.lineno}: {e.msg}: {(e.text or '').strip()}") from None
    n = 0
    for node in ast.walk(tree):
        n += 1
        ln = getattr(node, "lineno", "?")
        if n > 20_000:
            raise PolicyError("script too complex")
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS:
                    raise PolicyError(f"line {ln}: import of '{a.name}' is not allowed "
                                      f"(allowed: {sorted(ALLOWED_IMPORTS)})")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "") not in ALLOWED_IMPORTS:
                raise PolicyError(f"line {ln}: 'from {node.module} import ...' is not allowed "
                                  f"(allowed: {sorted(ALLOWED_IMPORTS)})")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise PolicyError(f"line {ln}: access to private/dunder attribute '{node.attr}' is not allowed")
            if node.attr in DENY_ATTRS:
                raise PolicyError(f"line {ln}: attribute '.{node.attr}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in DENY_NAMES or node.id.startswith("__"):
                raise PolicyError(f"line {ln}: name '{node.id}' is not allowed")
        elif isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            raise PolicyError(f"line {ln}: {type(node).__name__} is not allowed")
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("__"):
            raise PolicyError(f"line {ln}: dunder function names are not allowed")


@dataclass
class SandboxResult:
    ok: bool
    spec: Optional[dict] = None
    xosc: Optional[str] = None
    issues: list = field(default_factory=list)       # validator issues (dicts)
    margins: Optional[dict] = None                   # nominal-walker robustness margins per task id
    error: Optional[str] = None                      # policy / runtime / timeout error text

    def feedback(self) -> str:
        """Compact text for the agent loop."""
        if self.error:
            return f"ERROR: {self.error}"
        lines = []
        for i in self.issues:
            lines.append(f"[{i['severity'].upper()}] {i['code']}: {i['message']}")
        if self.ok:
            lines.insert(0, "OK: script accepted." + (" Warnings:" if lines else ""))
        else:
            lines.insert(0, "REJECTED: fix the errors below and submit again.")
        return "\n".join(lines)


# ----------------------------------------------------------------- host side
def run_script(code: str, map_json: str | Path, roadfile: str = "map.xodr", timeout: float = 30.0,
               mem_mb: int = 1536, spec: Optional[dict] = None, level: int = 2) -> SandboxResult:
    try:
        check_policy(code)
    except PolicyError as e:
        return SandboxResult(False, error=str(e))
    src = str(Path(__file__).resolve().parents[1])
    paths = [src] + [p for p in sys.path if "site-packages" in p or "dist-packages" in p]
    payload = json.dumps({"code": code, "map": str(map_json), "roadfile": roadfile, "paths": paths,
                          "mem_mb": mem_mb, "spec": spec, "level": level})
    env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "PATH")}
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="usg_sbx_") as tmp:
        popen_kw: dict = {}
        if os.name == "nt":
            popen_kw["creationflags"] = 0x08000000      # CREATE_NO_WINDOW
        boot = f"import sys; sys.path.insert(0, {src!r}); from usg.sandbox import _child_main; _child_main()"
        # In a venv, python.exe is a launcher that spawns the real interpreter as a 2nd process, which the 1-process job
        # limit below would refuse. Run the base interpreter directly; the venv's site-packages travel in ``paths``.
        interpreter = getattr(sys, "_base_executable", None) or sys.executable
        proc = subprocess.Popen([interpreter, "-E", "-B", "-c", boot], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp, env=env,
                                text=True, encoding="utf-8", **popen_kw,
                                **({} if os.name == "nt" else {"preexec_fn": _posix_limits(mem_mb, timeout)}))
        job = _assign_job(proc, mem_mb) if os.name == "nt" else None
        try:
            out, err = proc.communicate(payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return SandboxResult(False, error=f"script timed out after {timeout:.0f}s (infinite loop or too heavy)")
        finally:
            if job:
                _close_job(job)
    marker = "\n@@USG_RESULT@@"
    if marker not in out:
        tail = (err or out or "").strip().splitlines()[-6:]
        return SandboxResult(False, error="sandbox crashed: " + " | ".join(tail)[:600])
    data = json.loads(out.split(marker, 1)[1])
    return SandboxResult(ok=data["ok"], spec=data.get("spec"), xosc=data.get("xosc"),
                         issues=data.get("issues", []), error=data.get("error"), margins=data.get("margins"))


def _posix_limits(mem_mb: int, timeout: float):
    def f():
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2**20, mem_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_CPU, (int(timeout) + 5, int(timeout) + 5))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    return f


def _assign_job(proc, mem_mb: int):
    """Windows: put the child in a Job Object with a process-memory cap and kill-on-close."""
    try:
        import ctypes
        from ctypes import wintypes

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("a", "b", "c", "d", "e", "f")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        job = k.CreateJobObjectW(None, None)
        info = EXT()
        # JOB_OBJECT_LIMIT_PROCESS_MEMORY | KILL_ON_JOB_CLOSE | ACTIVE_PROCESS(1 process)
        info.BasicLimitInformation.LimitFlags = 0x100 | 0x2000 | 0x8
        info.BasicLimitInformation.ActiveProcessLimit = 1
        info.ProcessMemoryLimit = mem_mb * 2**20
        k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        k.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))
        return job
    except Exception:
        return None


def _close_job(job) -> None:
    try:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(job)
    except Exception:
        pass


# ----------------------------------------------------------------- child side
def _fmt_exc(code: str) -> str:
    et, ev, tb = sys.exc_info()
    lines = code.splitlines()
    frames = [f for f in traceback.extract_tb(tb) if f.filename == "<scenario>"]
    where = ""
    if frames:
        f = frames[-1]
        src = lines[f.lineno - 1].strip() if 0 < f.lineno <= len(lines) else ""
        where = f" at line {f.lineno}: `{src}`"
    return f"{et.__name__}: {ev}{where}"


def execute_script(code: str, model, roadfile: str = "map.xodr", spec: Optional[dict] = None, level: int = 2) -> dict:
    """Policy-check, run and validate a scenario script in THIS process.

    Runs inside the sandboxed child process (see ``run_script``). Never raises: returns a result dict.
    """
    res: dict = {"ok": False}
    try:
        check_policy(code)
        import builtins as _b
        import math
        import usg.dsl as dsl
        from usg.validate import validate

        MAP = dsl.MapQuery(model)

        def _imp(name, globals=None, locals=None, fromlist=(), level=0):
            if name not in ALLOWED_IMPORTS:
                raise ImportError(f"import of '{name}' is not allowed")
            return __import__(name, globals, locals, fromlist, level)

        safe = {n: getattr(_b, n) for n in SAFE_BUILTINS}
        safe["print"] = lambda *a, **k: None
        safe["__import__"] = _imp
        g: dict = {"__builtins__": safe, "__name__": "scenario", "MAP": MAP, "math": math}
        if spec is not None:
            import copy as _copy
            g["SPEC"] = _copy.deepcopy(spec)                  # the accepted specification document (plain data)
            accepted_spec = _copy.deepcopy(spec)
            dsl.builder.SPEC_LEVEL = level
        for n in dsl.__all__:
            g[n] = getattr(dsl, n)
        exec(compile(code, "<scenario>", "exec"), g)
        sc = g.get("scenario")
        if not isinstance(sc, dsl.ScenarioBuilder):
            res["error"] = ("the script must define a variable named `scenario` holding a ScenarioBuilder "
                            f"(found: {type(sc).__name__})")
        else:
            spec = sc.to_spec()
            from usg.spec import oracle
            try:
                margins = oracle.margins(spec, model)
            except Exception:                                   # the nominal walker is advisory: never block on its bugs
                margins = {}
            issues = validate(spec, model, margins)
            res["margins"] = {str(k): v for k, v in margins.items()}
            if g.get("SPEC") is not None and not any(t.get("explicit_spec") for t in spec["tasks"]):
                from usg.validate import Issue
                issues.append(Issue("error", "spec_not_applied",
                                    "the accepted specification was not applied: call `handles = scenario.apply_spec(SPEC)` in the script "
                                    "(and do not add go_to/cross/follow_path tasks)"))
            elif g.get("SPEC") is not None and len([t for t in spec["tasks"] if t.get("explicit_spec")]) != len(accepted_spec["tasks"]):
                from usg.validate import Issue
                issues.append(Issue("error", "spec_partially_applied", "apply_spec(SPEC) must create all tasks of the specification"))
            elif g.get("SPEC") is not None:
                import json as _json
                from usg.validate import Issue
                applied = [_json.dumps({"n": t["name"], "g": (t.get("spec_raw") or {}).get("goal"), "s": (t.get("spec_raw") or {}).get("safety")}, sort_keys=True)
                           for t in spec["tasks"] if t.get("explicit_spec")]
                wanted = [_json.dumps({"n": t["name"], "g": t["goal"], "s": list(t.get("safety", []))}, sort_keys=True) for t in accepted_spec["tasks"]]
                if applied != wanted:
                    issues.append(Issue("error", "spec_modified",
                                        "the script applied a DIFFERENT specification than the accepted one (it redefined SPEC or edited it). Do not write your own "
                                        "SPEC in the script: call `handles = scenario.apply_spec(SPEC)` with the SPEC you were given"))
            res["spec"] = spec
            res["issues"] = [i.to_dict() for i in issues]
            res["ok"] = not any(i.severity == "error" for i in issues)
            if res["ok"]:
                res["xosc"] = sc.to_xml_string(roadfile)
    except PolicyError as e:
        res["error"] = str(e)
    except Exception:
        res["error"] = _fmt_exc(code)
    return res


def _child_main() -> None:
    req = json.loads(sys.stdin.read())
    for p in reversed(req["paths"]):
        if p not in sys.path:
            sys.path.insert(0, p)
    if os.name != "nt":
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (req["mem_mb"] * 2**20,) * 2)
        except Exception:
            pass
    sys.setrecursionlimit(400)
    try:
        from usg.mapmodel import MapModel
        res = execute_script(req["code"], MapModel.load(req["map"]), req["roadfile"], req.get("spec"), req.get("level", 2))
    except Exception:
        res = {"ok": False, "error": _fmt_exc(req["code"])}
    sys.stdout.write("\n@@USG_RESULT@@" + json.dumps(res))
    sys.stdout.flush()


if __name__ == "__main__":
    _child_main()
