"""What a worker runs for one episode.

The worker owns queueing, heartbeats and persistence; an `EpisodeRunner` only turns an `EpisodeSpec`
into an `EpisodeResult`. It is called on the worker's main thread (MuJoCo rendering requires it), while
heartbeats are sent from a background thread.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


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


class HarnessRunner:
    """ADAPTER STUB: drives the robomcp agent harness (src/robomcp/agent) for one episode.

    To be implemented by the harness owner. Expected shape:
      1. reset the sim with `spec.seed` (and the perturbation settings in `spec.task` / `spec.agent_config`),
      2. build a `Harness` from `spec.agent_config` (mode, model, prompts) and run `spec.task["goal"]`,
      3. score with the task's scene-based check (ground truth, never the model's claim),
      4. upload the trace / episode log to object storage and return their URIs with metrics
         (steps, tokens, wall time, ...).
    """

    def run(self, spec: EpisodeSpec) -> EpisodeResult:
        raise NotImplementedError(
            "HarnessRunner is a stub: wire the robomcp harness in robomcp_platform/runner.py "
            "or set ROBOMCP_WORKER_RUNNER to another 'module:factory'"
        )
