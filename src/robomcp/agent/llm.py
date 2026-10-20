"""Chat client for OpenAI-compatible APIs (DeepSeek or Gemini) plus MCP → function-calling schema conversion."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_env(path: Path = PROJECT_ROOT / ".env") -> None:
    """Read KEY=VALUE lines from .env into os.environ (without overriding what is already set)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Usage:
    """Token accounting across all model calls of one run. DeepSeek reports prefix-cache hits separately."""

    calls: int = 0
    prompt: int = 0
    cache_hit: int = 0
    completion: int = 0

    def add(self, u) -> None:
        self.calls += 1
        self.prompt += u.prompt_tokens or 0
        self.completion += u.completion_tokens or 0
        # DeepSeek reports prompt_cache_hit_tokens; OpenAI-style APIs (Gemini) report prompt_tokens_details.cached_tokens
        details = getattr(u, "prompt_tokens_details", None)
        self.cache_hit += (getattr(u, "prompt_cache_hit_tokens", 0) or 0) or (getattr(details, "cached_tokens", 0) or 0)

    @property
    def hit_rate(self) -> float:
        return self.cache_hit / self.prompt if self.prompt else 0.0


PROVIDERS = {
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-flash-latest"),
}


def _keychain(service: str) -> str:
    out = subprocess.run(["security", "find-generic-password", "-s", service, "-w"], capture_output=True, text=True)
    return out.stdout.strip()


@dataclass
class LLM:
    """Provider: LLM_PROVIDER env, else DeepSeek if DEEPSEEK_API_KEY is set, else Gemini (key from the macOS Keychain)."""

    model: str = ""
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        load_env()
        self.provider = os.environ.get("LLM_PROVIDER") or ("deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "gemini")
        base_url, default_model = PROVIDERS[self.provider]
        if self.provider == "deepseek":
            key = os.environ.get("DEEPSEEK_API_KEY")
        else:
            key = os.environ.get("GEMINI_API_KEY") or _keychain("gemini-api-key")
        if not key:
            raise SystemExit(f"no API key for {self.provider} (set it in {PROJECT_ROOT / '.env'} or the Keychain)")
        self.model = self.model or os.environ.get("LLM_MODEL", default_model)
        self.client = OpenAI(api_key=key, base_url=base_url, max_retries=5)

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        kwargs = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            kwargs["tools"] = tools
        resp = self.client.chat.completions.create(**kwargs)
        self.usage.add(resp.usage)
        return resp.choices[0].message


def mcp_to_openai_tools(mcp_tools, exclude: set[str]) -> list[dict]:
    """MCP tool list → OpenAI/DeepSeek function-calling definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema or {"type": "object", "properties": {}},
            },
        }
        for t in mcp_tools
        if t.name not in exclude
    ]
