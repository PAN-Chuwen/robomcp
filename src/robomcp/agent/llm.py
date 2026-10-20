"""DeepSeek chat client (OpenAI-compatible API) plus MCP → function-calling schema conversion."""

from __future__ import annotations

import os
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
        self.cache_hit += getattr(u, "prompt_cache_hit_tokens", 0) or 0

    @property
    def hit_rate(self) -> float:
        return self.cache_hit / self.prompt if self.prompt else 0.0


@dataclass
class LLM:
    model: str = ""
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        load_env()
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise SystemExit(f"DEEPSEEK_API_KEY is not set (put it in {PROJECT_ROOT / '.env'})")
        self.model = self.model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.client = OpenAI(api_key=key, base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))

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
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for t in mcp_tools
        if t.name not in exclude
    ]
