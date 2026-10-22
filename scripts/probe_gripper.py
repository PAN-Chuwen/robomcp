"""Probe: jaw opening at each gripper command, and gripper position after closing on a cube vs on nothing.

    uv run python scripts/probe_gripper.py
"""

import numpy as np

from robomcp.sim import APPROACH_HEIGHT, GRIPPER_CLOSED, GRIPPER_OPEN, GRIPPER_RELEASE, TabletopSim

sim = TabletopSim()
LAYOUT = {"red_cube": (0.20, 0.06), "green_cube": (0.24, -0.08), "blue_cube": (0.15, -0.10)}
m, d = sim.model, sim.data


def jaw_gap() -> float:
    """Distance between the inner tip spheres of the fixed and moving jaw (minimum over tip pairs)."""
    fixed = [d.geom_xpos[m.geom(f"fixed_jaw_sph_tip{i}").id] for i in (1, 2, 3)]
    moving = [d.geom_xpos[m.geom(f"moving_jaw_sph_tip{i}").id] for i in (1, 2, 3)]
    return min(np.linalg.norm(a - b) for a in fixed for b in moving)


sim.reset(LAYOUT)
for cmd in (GRIPPER_OPEN, GRIPPER_RELEASE, 0.0, GRIPPER_CLOSED):
    d.ctrl[5] = cmd
    sim._settle(200)
    print(f"command {cmd:+.2f} rad -> jaw gap {jaw_gap() * 1000:5.1f} mm")


def close_at(dx: float) -> tuple[float, bool]:
    sim.reset(LAYOUT)
    x, y, z = sim.object_state("red_cube").position
    sim.set_gripper(True)
    sim.move_to(x + dx, y, z + APPROACH_HEIGHT)
    sim.move_to(x + dx, y, z + 0.002, 0.8)
    sim.set_gripper(False)
    sim.move_to(x + dx, y, z + APPROACH_HEIGHT, 0.8)
    return float(d.qpos[sim._grip_qadr]), sim.held_object() == "red_cube"


print("\ngripper joint after close + lift (truth: held?)")
for dx in (0.0, 0.004, 0.008, 0.012, 0.03, -0.03):
    q, held = close_at(dx)
    print(f"  grasp offset {dx * 1000:+5.1f} mm -> q {q:+.3f} rad  held={held}")
