# Security model for LLM-written scripts

The original prototype ran model output through `exec()` with `os` and `sys` in scope. Here every script is untrusted.

1. **Static policy** (`sandbox.check_policy`, AST based) rejects imports outside `usg.dsl`, `math`, `typing`, `scenariogeneration(.xosc)`; any
   attribute starting with `_`; names such as `eval exec open getattr type object os sys subprocess`; class definitions and async code;
   `str.format`/`format_map` (format-string attribute escapes); file/serialisation methods (`write_xml`, `read`, `dump`, …); oversize scripts.
2. **Restricted runtime**: a tiny builtins table, `print` is a no-op, `__import__` only returns whitelisted modules.
3. **Process isolation**: the script runs in a *child interpreter* (`sandbox.run_script`) with a scrubbed environment, a temp working
   directory, a wall-clock timeout and a memory cap (Windows Job Object / POSIX `RLIMIT_AS`). The Gradio server process never executes
   model-written code itself (`tools.submit_script` always goes through the child).
4. **No file writes by scripts**: the host serialises results; `Scenario.write_*` is blocked by the policy.
5. **Validation**: a script is accepted only if the map-aware validator passes.

## What this is not
Python cannot be perfectly sandboxed from inside Python. These layers defend against a *misbehaving model*, not a determined attacker with
unlimited attempts. If you expose the app beyond localhost (`usg app --host 0.0.0.0`) or share it with others, run it in a container/VM.
By default the app binds to 127.0.0.1 only.

Tests: `tests/test_pipeline.py` covers 12 escape patterns, an infinite loop and a memory bomb.

## The specification stage is data, not code (levels 1 and 2)
In the two-stage pipeline the model first writes a *task specification* (`usg.spec`). It is JSON that is parsed and type-checked
(`spec.formula.check_node`, `prepare`) and then interpreted by the monitor. No part of it is ever passed to `exec`/`eval`.
Own definitions (`defs`, level 2) are macros: they are expanded by substitution with hard limits (at most 12 definitions, call depth 6, no
recursion, 400 nodes and depth 14 after expansion), so a hostile or confused specification cannot loop or blow up memory.
The world script of the second stage still runs in the sandbox above; it receives the accepted specification as a plain `SPEC` dict.
The *nominal walker* (`spec/oracle.py`) is an offline validation device: it never runs in the player and never moves the participant.
