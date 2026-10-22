"""Replay must reproduce a run exactly and point at the first step where it does not."""

from __future__ import annotations

import asyncio
import json

import mujoco
import pytest

import robomcp.server as server
from robomcp.agent.harness import TRACE_VERSION
from robomcp.agent.replay import compare, load_run, replay
from robomcp.sim import TabletopSim

CALLS = [("harness", "reset_scene", {"seed": 1}), ("harness", "get_scene", {}),
         ("executor", "pick", {"object_name": "red_cube"}), ("executor", "place_in_tray", {}),
         ("harness", "get_scene", {})]


def _record(path, slip=0.0, slip_mode="immediate"):
    """Drive the server tools like the harness does: a v3 trace plus the environment's episode log (no LLM)."""
    sim = server.sim = TabletopSim()
    sim._live_dir = None
    sim.slip, sim.slip_mode = slip, slip_mode
    log = path.with_name(path.stem + ".env.jsonl")
    server.episode = server.EpisodeLog(log)
    events = [{"kind": "start", "goal": "把红色方块放进托盘", "mode": "bare", "seed": 1, "slip": slip,
               "slip_mode": slip_mode, "trace_version": TRACE_VERSION, "episode_log": log.name,
               "mujoco": mujoco.__version__}]
    for step, (by, name, args) in enumerate(CALLS):
        asyncio.run(getattr(server, name)(**args))
        events.append({"kind": "tool" if by == "executor" else "harness_call", "name": name, "args": args,
                       "step": step})
    events.append({"kind": "scored_steps", "before": 1, "after": len(CALLS) - 1})
    server.episode = None
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events))
    return log


def _steps(log):
    return [json.loads(line) for line in log.read_text().splitlines()][1:]


def test_replay_reproduces_every_step(tmp_path):
    trace = tmp_path / "run.jsonl"
    _record(trace)
    rep = asyncio.run(replay(trace, render=False))
    assert [s.name for s in rep.steps] == [c[1] for c in CALLS]
    assert rep.divergence is None
    assert rep.success is True


def test_replay_reproduces_delayed_silent_failure(tmp_path):
    # Seed 1 slips on the first placement; with "delayed" only the final get_scene shows the cube out of the tray.
    trace = tmp_path / "run.jsonl"
    steps = _steps(_record(trace, slip=0.5, slip_mode="delayed"))
    assert steps[3]["observation"]["scene"]["objects"][0]["in_tray"] is True  # place_in_tray looks fine...
    assert steps[-1]["truth"]["objects"][0]["in_tray"] is False  # ...until the next observation
    rep = asyncio.run(replay(trace, render=False))
    assert rep.divergence is None
    assert rep.success is False


def test_replay_reports_first_divergent_step(tmp_path):
    trace = tmp_path / "run.jsonl"
    log = _record(trace)
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    lines[3]["truth"]["objects"][0]["position"][0] += 0.05  # step 2 (pick): the logged truth no longer matches
    log.write_text("\n".join(json.dumps(r) for r in lines))
    rep = asyncio.run(replay(trace, render=False))
    assert rep.divergence is not None and rep.divergence.name == "pick"
    assert rep.divergence.drift_m == pytest.approx(0.05, abs=1e-3)


def test_compare_flags_discrete_changes():
    scene = {"objects": [{"name": "a", "position": [0, 0, 0], "in_tray": True}], "gripper": {"holding": None}}
    moved = {"objects": [{"name": "a", "position": [0, 0, 0], "in_tray": False}], "gripper": {"holding": "a"}}
    drift, mismatches = compare({"ok": True, "scene": scene}, {"ok": False, "scene": moved})
    assert drift == 0.0
    assert len(mismatches) == 3


def test_episode_log_hides_truth_from_observation(tmp_path):
    steps = _steps(_record(tmp_path / "run.jsonl"))
    pick = steps[2]
    assert pick["observation"]["scene"]["gripper"]["holding"] is True  # the agent only knows it holds something
    assert pick["truth"]["gripper"]["holding"] == "red_cube"


def test_rejects_old_trace(tmp_path):
    trace = tmp_path / "old.jsonl"
    trace.write_text(json.dumps({"kind": "start", "goal": "x", "trace_version": 2}))
    with pytest.raises(ValueError, match="trace v3"):
        load_run(trace)
