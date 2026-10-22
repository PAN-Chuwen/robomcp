"""Deterministic safety gate between an agent's command and its execution.

Only commands that carry free coordinates are checked (move_to, place_at); named skills compute their own
targets. The rules are geometric and need no perception, so the gate cannot be fooled by a wrong scene
estimate. A blocked command is not executed and is reported with `blocked: true`, so evals can count it.
"""

from __future__ import annotations

import math

# Box the gripper tip may be sent to (metres, robot base frame); the table surface is z = 0.
WORKSPACE = {"x": (0.05, 0.33), "y": (-0.25, 0.28), "z": (0.005, 0.25)}
BASE_KEEPOUT_M = 0.10  # horizontal radius around the arm's base: targets inside it fold the arm into itself
GATED_TOOLS = {"move_to", "place_at"}


def check(tool: str, args: dict) -> str | None:
    """Reason the command is unsafe, or None if it may run."""
    if tool not in GATED_TOOLS:
        return None
    for axis, (lo, hi) in WORKSPACE.items():
        if axis not in args:
            continue
        v = args[axis]
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            return f"{axis}={v!r} is not a finite number"
        if not lo <= v <= hi:
            return f"{axis}={v} m is outside the workspace [{lo}, {hi}] m"
    if math.hypot(args.get("x", 1.0), args.get("y", 1.0)) < BASE_KEEPOUT_M:
        return f"target is within {BASE_KEEPOUT_M} m of the arm's base"
    return None
