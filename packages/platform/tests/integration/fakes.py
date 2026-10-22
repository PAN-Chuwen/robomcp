"""Test-only EpisodeRunner implementations and fixtures data."""

from __future__ import annotations

from collections.abc import Callable

from robomcp_platform.runner import EpisodeResult, EpisodeSpec

TASKS = [{"key": "red", "goal": "put the red cube in the tray"},
         {"key": "all", "goal": "put every cube in the tray"}]


class FakeRunner:
    """Deterministic runner: success decided by `decide(spec)`; records every spec it ran."""

    def __init__(self, decide: Callable[[EpisodeSpec], bool] | None = None,
                 before_return: Callable[[EpisodeSpec], None] | None = None):
        self.decide = decide or (lambda spec: spec.seed % 2 == 0)
        self.before_return = before_return
        self.calls: list[EpisodeSpec] = []

    def run(self, spec: EpisodeSpec) -> EpisodeResult:
        self.calls.append(spec)
        if self.before_return:
            self.before_return(spec)
        return EpisodeResult(
            success=self.decide(spec),
            metrics={"steps": 3, "seed": spec.seed},
            trace_uri=f"s3://robomcp/traces/{spec.episode_id}.jsonl",
            episode_log_uri=f"s3://robomcp/logs/{spec.episode_id}.json",
        )


class RaisingRunner:
    def __init__(self, exc: Exception | None = None):
        self.exc = exc or RuntimeError("sim crashed")
        self.calls = 0

    def run(self, spec: EpisodeSpec) -> EpisodeResult:
        self.calls += 1
        raise self.exc
