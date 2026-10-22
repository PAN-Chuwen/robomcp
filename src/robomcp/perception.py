"""Perception: where the agent's view of object positions comes from.

The simulator knows the true pose of every object; a robot does not. Everything the agent sees, and every
skill target, goes through a Perception, so perception error turns into missed grasps the way it would on a
real arm (the grasp tolerance is about 6 mm, scripts/probe_grasp.py). Ground truth stays with the
environment for scoring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np

if TYPE_CHECKING:
    from robomcp.sim import TabletopSim


class Perception(Protocol):
    name: str

    def detect(self, sim: TabletopSim) -> dict[str, np.ndarray]:
        """Estimated position (x, y, z in metres, base frame) of each object the perception can see."""
        ...


class OraclePerception:
    """Perfect perception: the true positions. The upper bound that real detectors are compared against."""

    name = "oracle"

    def detect(self, sim: TabletopSim) -> dict[str, np.ndarray]:
        return {n: sim.data.xpos[sim.model.body(n).id].copy() for n in sim.objects}
