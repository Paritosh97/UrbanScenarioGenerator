"""The planning agent: a tool-using loop between an LLM and the tool server.

The protocol is forgiving for small models: one ``<tool name="...">`` per message, JSON arguments or, for
``submit_script``, a fenced python block. A bare ```python block that defines ``scenario`` counts as a
submission. ``run_agent`` is a generator (it streams events to the UI); the last event is ``done`` or ``failed``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional, Protocol

from ..tools import ToolServer, system_prompt


class Chat(Protocol):
    context_tokens: int

    def chat(self, messages: list[dict], max_tokens: int = ..., on_token: Optional[Callable[[str], None]] = ...) -> str: ...


TOOL_RE = re.compile(r"<tool\s+name\s*=\s*[\"']?([a-z_]+)[\"']?\s*>(.*?)(?:</tool>|\Z)", re.I | re.S)
FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.I | re.S)
THINK_RE = re.compile(r"<think>.*?</think>", re.I | re.S)
JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)```", re.I | re.S)
SUBMITS = ("submit_script", "submit_spec")


def strip_thinking(s: str) -> str:
    """Drop reasoning blocks (Qwen3/3.5) so they can neither hide nor fake a tool call."""
    s = THINK_RE.sub("", s)
    return re.sub(r"^.*?</think>", "", s, count=1, flags=re.I | re.S)


@dataclass
class ParsedTool:
    name: str
    args: dict


def _tolerant_json(s: str) -> dict:
    t = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.I).strip()
    if not t:
        return {}
    for cand in (t, re.sub(r",\s*([}\]])", r"\1", t).replace("'", '"')):
        try:
            v = json.loads(cand)
            return v if isinstance(v, dict) else {}
        except ValueError:
            pass
    m = re.search(r"\{.*\}", re.sub(r",\s*([}\]])", r"\1", t).replace("'", '"'), re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    raise ValueError("arguments are not valid JSON")


def parse_tool_call(raw: str) -> Optional[ParsedTool]:
    reply = strip_thinking(raw)
    m = TOOL_RE.search(reply)
    if m:
        name, body = m.group(1).lower(), m.group(2)
        if name == "submit_script":
            f = FENCE_RE.search(body)
            code = (f.group(1) if f else re.sub(r"^```(?:python)?|```$", "", body, flags=re.I | re.M)).strip()
            return ParsedTool(name, {"code": code})
        return ParsedTool(name, _tolerant_json(body))
    f = FENCE_RE.search(reply)
    if f and re.search(r"\bscenario\s*=", f.group(1)):
        return ParsedTool("submit_script", {"code": f.group(1).strip()})
    j = JSON_FENCE_RE.search(reply)
    if j and '"tasks"' in j.group(1) and '"goal"' in j.group(1):         # a bare ```json specification counts as a submission
        return ParsedTool("submit_spec", _tolerant_json(j.group(1)))
    return None


def _clen(c) -> int:
    """Characters of a message; an attached image counts as ~2,500 characters (~800 tokens)."""
    if isinstance(c, str):
        return len(c)
    return sum(len(p.get("text", "")) + (2500 if p.get("type") == "image_url" else 0) for p in c)


def _tokens(msgs: list[dict]) -> int:
    return int(sum(_clen(m["content"]) for m in msgs) / 3.2)


def compact(msgs: list[dict], budget: int) -> list[dict]:
    """Shrink old tool results first once the conversation nears the context window."""
    out = [dict(m) for m in msgs]
    i = 2
    while i < len(out) - 4 and _tokens(out) > budget:
        c = out[i]["content"]
        if not isinstance(c, str):
            i += 1
            continue
        if out[i]["role"] == "user" and c.startswith("Tool result"):
            out[i]["content"] = c[:160] + " ...[truncated]"
        elif out[i]["role"] == "assistant" and len(c) > 400 and "submit_script" not in c:
            out[i]["content"] = c[:300] + " ..."
        i += 1
    return out


def _summarise(name: str, r: dict) -> str:
    if name in SUBMITS:
        return " | ".join((r.get("feedback") or r.get("error") or "").split("\n")[:3])[:300]
    if not r.get("ok", True):
        return r.get("error", "error")
    s = json.dumps({k: v for k, v in r.items() if k != "ok"})
    return s if len(s) <= 140 else s[:137] + "..."


def _render(name: str, r: dict) -> str:
    if name in SUBMITS:
        return f"Tool result ({name}):\n{r.get('feedback') or r.get('error') or json.dumps(r)}"
    s = json.dumps({k: v for k, v in r.items() if k != "ok"} if r.get("ok") else {"error": r.get("error")})
    return f"Tool result ({name}):\n" + (s if len(s) <= 2600 else s[:2600] + " ...[truncated]")


def run_agent(llm: Chat, tools: ToolServer, prompt: str, max_steps: int = 16,
              on_token: Optional[Callable[[str], None]] = None) -> Iterator[dict[str, Any]]:
    """Yield events: thinking | token | tool | result | warning | done | failed."""
    from .. import grounding
    from ..scenario_types import ARCHETYPES, classify
    tools.prompt = prompt
    refusal = grounding.refusal_text(prompt, tools.q) if tools.q is not None else None
    if refusal:                                       # hard check: the request names something this map does not contain
        yield {"kind": "warning", "text": refusal}
        yield {"kind": "failed", "steps": 0, "reason": refusal}
        return
    level = getattr(tools, "level", 0)
    if level >= 1:
        max_steps = max(max_steps, 22)
    # Small models over-explore, so the harness does the two obvious first calls itself (and shows them in the log):
    # the map overview and the reference script of the most likely scenario type.
    guess = classify(prompt)[0]
    overview = tools.call("get_map_overview")
    template = tools.call("get_scenario_template", {"type": guess})
    yield {"kind": "tool", "step": 0, "name": "get_map_overview", "args": {"auto": True}}
    yield {"kind": "result", "step": 0, "name": "get_map_overview", "ok": overview.get("ok", False), "summary": _summarise("get_map_overview", overview)}
    yield {"kind": "tool", "step": 0, "name": "get_scenario_template", "args": {"type": guess, "auto": True}}
    yield {"kind": "result", "step": 0, "name": "get_scenario_template", "ok": template.get("ok", False), "summary": f"reference script for {guess}"}
    if level == 0:
        first = (
            f"Request: {prompt}\n\nMap overview: {json.dumps({k: v for k, v in overview.items() if k != 'ok'})[:1800]}\n{grounding.inventory_text(tools.q)}\n\n"
            f"Most likely scenario type: {guess}. Here is its working reference script (it adapts to this map by itself):\n"
            f"```python\n{template.get('script', '')}\n```\n"
            "Adapt it to the request (texts, speeds, timeouts, which crossing/landmark), then call submit_script. "
            "If the type is clearly wrong, call get_scenario_template with the right type first.")
    else:
        from ..sandbox import run_script
        from ..spec.document import document_from_spec
        ref = run_script(ARCHETYPES[guess]["template"], tools.map_path, "map.xodr")
        ref_doc = document_from_spec(ref.spec) if ref.ok and ref.spec else {"tasks": []}
        yield {"kind": "tool", "step": 0, "name": "reference_specification", "args": {"type": guess, "auto": True}}
        yield {"kind": "result", "step": 0, "name": "reference_specification", "ok": bool(ref_doc["tasks"]),
               "summary": f"{len(ref_doc['tasks'])} task(s) from the {guess} reference"}
        first = (
            f"Request: {prompt}\n\nMap overview: {json.dumps({k: v for k, v in overview.items() if k != 'ok'})[:1800]}\n{grounding.inventory_text(tools.q)}\n\n"
            f"Most likely scenario type: {guess}. Reference SPECIFICATION (what the participant must do; it was derived from a working "
            f"scenario on this map):\n```json\n{json.dumps(ref_doc)}\n```\n"
            f"Reference world script (go_to/cross/follow_path lines must become `handles = scenario.apply_spec(SPEC)` in your version):\n"
            f"```python\n{template.get('script', '')}\n```\n"
            "Step 1: adapt the specification to the request and call submit_spec. Step 2: submit the world script. "
            + ("You may define your own definitions in \"defs\" when the library does not express what is asked."
               if level >= 2 else "Use the library definitions."))
    if getattr(tools, "vision", False):
        from ..llm import with_image
        from ..render import map_image_png
        first += ("\n\nThe attached image is a top-down view of the map (north up, metres; grid lines every 25-50 m with coordinates; crossings are "
                  "labelled c<n> = crossing_<n>, bus stops bus<n>, roads road_<n>). Use it to choose places, but take ids and exact numbers from tool results.")
        content = with_image(first, map_image_png(tools.model))
        yield {"kind": "tool", "step": 0, "name": "map_image", "args": {"auto": True}}
        yield {"kind": "result", "step": 0, "name": "map_image", "ok": True, "summary": "annotated top-down map attached to the first message"}
    else:
        content = first
    messages: list[dict] = [
        {"role": "system", "content": system_prompt(level)},
        {"role": "user", "content": content},
    ]
    nudges = submits = lookups = spec_submits = 0
    last_spec_error = ""
    seen_calls: set[tuple] = set()
    last_submit_error = ""
    for step in range(1, max_steps + 1):
        reply = llm.chat(compact(messages, int(llm.context_tokens * 0.8)), 1800, on_token=on_token)
        messages.append({"role": "assistant", "content": reply})
        pre = re.split(r"<tool", strip_thinking(reply), flags=re.I)[0].strip()
        if pre:
            yield {"kind": "thinking", "step": step, "text": pre[:600]}
        call, err = None, ""
        try:
            call = parse_tool_call(reply)
        except ValueError as e:
            err = str(e)
        if call is None:
            nudges += 1
            if nudges > 4:
                yield {"kind": "failed", "steps": step, "reason": "model stopped calling tools"}
                return
            messages.append({"role": "user", "content": (
                f"Your tool call could not be read ({err}). Reply with exactly one <tool name=\"...\"> call." if err else
                'Reply with exactly one tool call: <tool name="NAME">{json}</tool>. '
                + ("If your specification is ready, call submit_spec; if it was accepted, call submit_script." if level else "If your script is ready, call submit_script."))})
            yield {"kind": "warning", "text": err or "no tool call found; asking the model again"}
            continue
        shown = ({"code": f"({len(call.args.get('code', '').splitlines())} lines)"} if call.name == "submit_script" else
                 {"tasks": len(call.args.get("tasks", [])) if isinstance(call.args.get("tasks"), list) else "?"} if call.name == "submit_spec" else call.args)
        yield {"kind": "tool", "step": step, "name": call.name, "args": shown}
        result = tools.call(call.name, call.args)
        ok = bool(result.get("accepted")) if call.name in SUBMITS else bool(result.get("ok"))
        yield {"kind": "result", "step": step, "name": call.name, "ok": ok, "summary": _summarise(call.name, result)}
        rendered = _render(call.name, result)
        sig = (call.name, json.dumps(call.args, sort_keys=True, default=str))
        if call.name not in SUBMITS:
            lookups += 1
            if sig in seen_calls:
                rendered += ("\nNOTE: you already made this exact call" + (" and it failed. Change the arguments (follow the example "
                             "in the tool list) or use a different tool." if not ok else ". You already have this result: use it and move on."))
                yield {"kind": "warning", "text": f"{call.name} repeated with identical arguments"}
            elif lookups >= 5:
                rendered += "\nNOTE: that is enough exploration. Write the script now and call submit_script."
            seen_calls.add(sig)
        elif call.name == "submit_spec":
            spec_submits += 1
            if not result.get("accepted"):
                err1 = next((ln for ln in str(result.get("feedback", "")).splitlines() if ln.startswith("[ERROR]")), "")
                if err1 and err1 == last_spec_error:
                    rendered += ("\nNOTE: this is the SAME error as before, so your edit did not fix it. Change exactly the part of the "
                                 "specification the error names (check the JSON path in the message).")
                    yield {"kind": "warning", "text": "same specification error again"}
                last_spec_error = err1
                if spec_submits >= 6:
                    messages.append({"role": "user", "content": rendered})
                    yield {"kind": "failed", "steps": step, "reason": "too many rejected specifications"}
                    return
        elif not result.get("accepted"):
            first = next((ln for ln in str(result.get("feedback", "")).splitlines() if ln.startswith(("[ERROR]", "ERROR"))), "")
            if first and first == last_submit_error:
                rendered += ("\nNOTE: this is the SAME error as your previous submission, so your edit did not fix it. Do not resubmit the "
                             "same code and do not go looking at unrelated features: change the exact part of the script that the error names.")
                yield {"kind": "warning", "text": "same validator error again"}
            last_submit_error = first
        messages.append({"role": "user", "content": rendered})
        if call.name == "submit_script":
            submits += 1
            if result.get("accepted"):
                yield {"kind": "done", "steps": step}
                return
            if submits >= 6:
                yield {"kind": "failed", "steps": step, "reason": "too many rejected scripts"}
                return
    yield {"kind": "failed", "steps": max_steps, "reason": "step limit reached"}
