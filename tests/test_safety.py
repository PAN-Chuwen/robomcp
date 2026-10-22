"""The safety gate blocks unsafe coordinates before anything moves."""

from __future__ import annotations

import asyncio

import pytest

import robomcp.server as server
from robomcp import safety
from robomcp.sim import TabletopSim


@pytest.mark.parametrize("args", [
    {"x": 0.2, "y": 0.0, "z": -0.01},   # into the table
    {"x": 0.5, "y": 0.0, "z": 0.05},    # beyond the workspace
    {"x": 0.03, "y": 0.02, "z": 0.05},  # inside the base keep-out
    {"x": float("nan"), "y": 0.0, "z": 0.05},
])
def test_blocks_unsafe_move(args):
    assert safety.check("move_to", args) is not None


@pytest.mark.parametrize("tool,args", [
    ("move_to", {"x": 0.2, "y": 0.05, "z": 0.08}),
    ("place_at", {"x": 0.1, "y": 0.22}),  # inside the tray
    ("pick", {"object_name": "red_cube"}),  # named skills are not gated
])
def test_allows_safe_commands(tool, args):
    assert safety.check(tool, args) is None


def test_blocked_command_does_not_move_the_arm():
    sim = server.sim = TabletopSim()
    sim._live_dir = None
    before = sim.tip_position()
    out = asyncio.run(server.move_to(0.2, 0.0, -0.05))
    assert out["ok"] is False and out["blocked"] is True
    assert (sim.tip_position() == before).all()
