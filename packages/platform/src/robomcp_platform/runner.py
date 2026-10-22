"""What a worker runs for one episode.

The worker owns queueing, heartbeats and persistence; an `EpisodeRunner` only turns an `EpisodeSpec`
into an `EpisodeResult`. It is called on the worker's main thread (MuJoCo rendering requires it), while
heartbeats are sent from a background thread.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from robomcp_platform.config import get_settings
from robomcp_platform.storage import ArtifactStore, make_store


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID
    experiment_id: uuid.UUID
    suite_version_id: uuid.UUID
    agent_version_id: uuid.UUID
    task_key: str
    task: dict[str, Any]  # the suite version's task object, including its `key`
    agent_config: dict[str, Any]
    seed: int
    repeat_index: int
    attempt: int  # 1-based


@dataclass(frozen=True)
class EpisodeResult:
    success: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    trace_uri: str | None = None
    episode_log_uri: str | None = None


@runtime_checkable
class EpisodeRunner(Protocol):
    def run(self, spec: EpisodeSpec) -> EpisodeResult:
        """Run one episode to completion. Raise to signal that no result could be produced."""
        ...


def resolve_task(task: dict[str, Any]):
    """The built-in robomcp task a suite task refers to (`check`, default its `key`), with its goal overridable.

    Success checks are code (scene-based, never the model's claim); suites pick one by name until M4 brings a
    scenario format with declarative checks.
    """
    from robomcp.agent.tasks import TASKS

    name = task.get("check", task["key"])
    builtin = next((t for t in TASKS if t.key == name), None)
    if builtin is None:
        raise ValueError(f"task {task['key']!r}: unknown check {name!r}, known: {[t.key for t in TASKS]}")
    return builtin, task.get("goal") or builtin.goal


class HarnessRunner:
    """Runs one episode with the robomcp agent harness (src/robomcp/agent) and scores it from ground truth.

    - `spec.task`: `key`, optional `goal`, `check` (a built-in task key, default `key`) and `perturbations`
      (`slip`, `slip_mode`: environment failure injection belongs to the scenario, not the agent).
    - `spec.agent_config`: `mode` (bare / verify / plan), optional `model`, `max_turns`, `max_verify`.
    - The scene seed is `spec.seed`; repeats share it, so they measure the agent's variance on one scene.
    - Success comes from the environment's episode log (ground truth), never from the agent's claim.
    - The trace and the episode log are uploaded under the episode's tenant-prefixed key, with their original
      file names so the trace's reference to its episode log stays valid for replay.
    """

    def __init__(self, store: ArtifactStore | None = None, llm_factory: Callable[[dict], Any] | None = None):
        self.store = store or make_store(get_settings())
        self.llm_factory = llm_factory  # tests inject a scripted LLM; default: robomcp's OpenAI-compatible client

    def _llm(self, cfg: dict[str, Any]):
        if self.llm_factory:
            return self.llm_factory(cfg)
        from robomcp.agent.llm import LLM

        return LLM(model=cfg.get("model", ""))

    def run(self, spec: EpisodeSpec) -> EpisodeResult:
        from robomcp.agent.harness import Harness

        task, goal = resolve_task(spec.task)
        pert, cfg = spec.task.get("perturbations", {}), spec.agent_config
        with tempfile.TemporaryDirectory(prefix="robomcp-episode-") as tmp:
            harness = Harness(mode=cfg.get("mode", "plan"), max_turns=cfg.get("max_turns", 20),
                              max_verify=cfg.get("max_verify", 2), verbose=False,
                              slip=float(pert.get("slip", 0.0)), slip_mode=pert.get("slip_mode", "immediate"),
                              llm=self._llm(cfg), trace_dir=Path(tmp))
            res = asyncio.run(harness.run(goal, seed=spec.seed))
            log = [json.loads(line) for line in Path(res.episode_log).read_text().splitlines()]
            prefix = f"{spec.org_id}/{spec.project_id}/{spec.experiment_id}/{spec.episode_id}/attempt-{spec.attempt}"
            trace_uri = self.store.put(f"{prefix}/{Path(res.trace_path).name}", Path(res.trace_path))
            log_uri = self.store.put(f"{prefix}/{Path(res.episode_log).name}", Path(res.episode_log))
        u = harness.llm.usage
        metrics = {
            "tool_calls": res.tool_calls, "verifier_rounds": res.verifier_rounds, "model_calls": u.calls,
            "prompt_tokens": u.prompt, "cache_hit_tokens": u.cache_hit, "seconds": res.seconds,
            "blocked_actions": sum(1 for r in log[1:] if isinstance(r["observation"], dict)
                                   and r["observation"].get("blocked")),
            "model": harness.llm.model, "fingerprint": log[0].get("fingerprint"),
        }
        return EpisodeResult(success=task.check(res.truth_before, res.truth_after), metrics=metrics,
                             trace_uri=trace_uri, episode_log_uri=log_uri)
