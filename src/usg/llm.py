"""Minimal client for any OpenAI-compatible chat server (Ollama, LM Studio, llama.cpp ``llama-server``, vLLM).

Standard library only. The model runs in that server (on your AMD iGPU through Vulkan/ROCm, or on an NVIDIA
eGPU through CUDA); this module only talks HTTP, so the same code works with every backend.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

PRESETS = {
    "Ollama": "http://localhost:11434/v1",
    "LM Studio": "http://localhost:1234/v1",
    "llama.cpp server": "http://localhost:8080/v1",
}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMClient:
    base_url: str = PRESETS["Ollama"]
    model: str = ""
    api_key: str = "not-needed"
    timeout: float = 600.0
    context_tokens: int = 12288          # used by the agent to compact its history
    temperature: float = 0.2
    local_extras: bool = True            # Qwen-style "no thinking" switches; set False for hosted APIs that reject unknown fields

    def _body(self, messages: list[dict], max_tokens: int) -> dict:
        body = {"model": self.model, "messages": messages, "stream": True, "temperature": self.temperature,
                "max_tokens": max_tokens}
        if self.local_extras:
            body["top_p"] = 0.9
            # Qwen3/3.5 style models: answer directly. Servers that do not know these fields ignore them.
            body.update({"chat_template_kwargs": {"enable_thinking": False}, "think": False})
        return body

    def _req(self, path: str, body: Optional[dict] = None) -> urllib.request.Request:
        url = self.base_url.rstrip("/") + path
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        return urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                      headers=headers, method="GET" if body is None else "POST")

    def list_models(self) -> list[str]:
        try:
            with urllib.request.urlopen(self._req("/models"), timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise LLMError(f"cannot reach {self.base_url} ({e}). Is the model server running?") from None
        return sorted(m["id"] for m in data.get("data", []))

    def chat(self, messages: list[dict], max_tokens: int = 1800,
             on_token: Optional[Callable[[str], None]] = None) -> str:
        """Stream a completion; stops as soon as a ``</tool>`` tag closes (one tool call per turn)."""
        if not self.model:
            raise LLMError("no model selected")
        body = self._body(messages, max_tokens)
        out: list[str] = []
        try:
            resp = urllib.request.urlopen(self._req("/chat/completions", body), timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise LLMError(f"server returned {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}") from None
        except (urllib.error.URLError, OSError) as e:
            raise LLMError(f"cannot reach {self.base_url} ({e})") from None
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    delta = json.loads(payload)["choices"][0].get("delta", {})
                except (ValueError, KeyError, IndexError):
                    continue
                tok = delta.get("content") or ""
                if tok:
                    out.append(tok)
                    if on_token:
                        on_token(tok)
                    if "".join(out[-6:]).rstrip().endswith("</tool>"):
                        break
        return "".join(out)


def with_image(text: str, png: bytes) -> list[dict]:
    """OpenAI-style multimodal message content: the text followed by one PNG image."""
    import base64
    return [{"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}}]
