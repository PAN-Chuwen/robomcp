"""Replay must reproduce a run exactly and point at the first step where it does not."""

from __future__ import annotations

import asyncio
import json

import mujoco
import pytest

import robomcp.server as server
from robomcp.agent.harness import TRACE_VERSION
from robomcp.agent.replay import compare, load_trace, replay
from robomcp.sim import TabletopSim

CALLS = [("harness", "reset_scene", {"seed": 1}), ("harness", "get_scene", {}),
         ("executor", "pick", {"object_name": "red_cube"}), ("executor", "place_in_tray", {}),
         ("harness", "get_scene", {})]


def _record(path, slip=0.0, slip_mode="immediate"):
    """Drive the server tools like the harness does and write a v2 trace (no LLM involved)."""
    sim = server.sim = TabletopSim()
    sim._live_dir = None
    sim.slip, sim.slip_mode = slip, slip_mode
    events = [{"kind": "start", "goal": "把红色方块放进托盘", "mode": "bare", "seed": 1, "slip": slip,
               "slip_mode": slip_mode, "trace_version": TRACE_VERSION, "mujoco": mujoco.__version__}]
    for by, name, args in CALLS:
        result = json.loads(json.dumps(asyncio.run(getattr(server, name)(**args))))
        kind = "tool" if by == "executor" else "harness_call"
        events.append({"kind": kind, "name": name, "args": args, "result": result})
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events))
    return events


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
    events = _record(trace, slip=0.5, slip_mode="delayed")
    assert events[-1]["result"]["objects"][0]["in_tray"] is False
    rep = asyncio.run(replay(trace, render=False))
    assert rep.divergence is None
    assert rep.success is False


def test_replay_reports_first_divergent_step(tmp_path):
    trace = tmp_path / "run.jsonl"
    events = _record(trace)
    events[3]["result"]["scene"]["objects"][0]["position"][0] += 0.05  # pick result no longer matches
    trace.write_text("\n".join(json.dumps(e) for e in events))
    rep = asyncio.run(replay(trace, render=False))
    assert rep.divergence is not None and rep.divergence.name == "pick"
    assert rep.divergence.drift_m == pytest.approx(0.05, abs=1e-3)


def test_compare_flags_discrete_changes():
    scene = {"objects": [{"name": "a", "position": [0, 0, 0], "in_tray": True}], "gripper": {"holding": None}}
    moved = {"objects": [{"name": "a", "position": [0, 0, 0], "in_tray": False}], "gripper": {"holding": "a"}}
    drift, mismatches = compare({"ok": True, "scene": scene}, {"ok": False, "scene": moved})
    assert drift == 0.0
    assert len(mismatches) == 3


def test_rejects_v1_trace(tmp_path):
    trace = tmp_path / "old.jsonl"
    trace.write_text(json.dumps({"kind": "start", "goal": "x"}))
    with pytest.raises(ValueError, match="trace v2"):
        load_trace(trace)
