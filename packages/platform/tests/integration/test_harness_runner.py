"""HarnessRunner end to end: real harness, MCP server subprocess and MuJoCo, with a scripted model."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fakes import PUT_RED_IN_TRAY, ScriptedLLM

from robomcp_platform.runner import EpisodeSpec, HarnessRunner, resolve_task
from robomcp_platform.storage import LocalStore
from robomcp_platform.worker import Worker


def _spec(task: dict, seed: int = 2) -> EpisodeSpec:
    ids = [uuid.uuid4() for _ in range(6)]
    return EpisodeSpec(*ids, task_key=task["key"], task=task, agent_config={"mode": "bare"}, seed=seed,
                       repeat_index=0, attempt=1)


def _runner(tmp_path: Path, calls=PUT_RED_IN_TRAY) -> HarnessRunner:
    return HarnessRunner(store=LocalStore(tmp_path / "artifacts"), llm_factory=lambda cfg: ScriptedLLM(calls))


def test_scores_success_and_stores_artifacts(tmp_path):
    result = _runner(tmp_path).run(_spec({"key": "red"}))
    assert result.success is True
    assert result.metrics["tool_calls"] == 3 and result.metrics["blocked_actions"] == 0
    assert set(result.metrics["fingerprint"]) == {"model", "code", "mujoco"}
    trace = Path(result.trace_uri.removeprefix("file://"))
    log = Path(result.episode_log_uri.removeprefix("file://"))
    start = json.loads(trace.read_text().splitlines()[0])
    assert start["episode_log"] == log.name  # replay can find the episode log next to the trace


def test_scores_from_truth_not_the_agents_claim(tmp_path):
    # Seed 1 slips on the first placement; with "delayed" the tool result still says the cube is in the tray
    # and the scripted agent declares success, but the episode log's truth does not.
    task = {"key": "red", "perturbations": {"slip": 0.5, "slip_mode": "delayed"}}
    result = _runner(tmp_path).run(_spec(task, seed=1))
    assert result.success is False


def test_counts_blocked_actions(tmp_path):
    calls = [("move_to", {"x": 0.2, "y": 0.0, "z": -0.05}), *PUT_RED_IN_TRAY]
    result = _runner(tmp_path, calls).run(_spec({"key": "red"}))
    assert result.metrics["blocked_actions"] == 1 and result.success is True


def test_unknown_check_is_rejected():
    with pytest.raises(ValueError, match="unknown check"):
        resolve_task({"key": "fold_towel"})


def test_worker_runs_an_experiment_end_to_end(make_org, sm, settings, tmp_path):
    org = make_org()
    exp = org.experiment([{"key": "red"}], seeds=[2], agent_config={"mode": "bare"})
    worker = Worker(sm, _runner(tmp_path), settings, "w-e2e")
    assert worker.run_once() is True
    episodes = org.ok("GET", f"/v1/experiments/{exp['id']}/episodes")
    ep = episodes[0] if isinstance(episodes, list) else episodes["items"][0]
    assert ep["status"] == "succeeded" and ep["trace_uri"].startswith("file://")
    summary = org.ok("GET", f"/v1/experiments/{exp['id']}")
    assert summary["status"] == "completed"
    assert summary["results"]["successes"] == summary["results"]["scored"] == 1
