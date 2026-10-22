"""Probe: grasp success vs cube yaw and vs grasp-target position error (simulated perception error).

    uv run python scripts/probe_grasp.py
"""
import math
import numpy as np, mujoco
from robomcp.sim import TabletopSim, APPROACH_HEIGHT

sim = TabletopSim()
LAYOUT = {"red_cube": (0.20, 0.06), "green_cube": (0.24, -0.08), "blue_cube": (0.15, -0.10)}

def set_yaw(name, yaw):
    adr = sim.model.joint(sim.model.body(name).jntadr[0]).qposadr[0]
    sim.data.qpos[adr + 3: adr + 7] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
    mujoco.mj_forward(sim.model, sim.data); sim._settle(50)

def trial(yaw_deg=0.0, dx=0.0, dy=0.0, grip_yaw=None):
    sim.reset(LAYOUT)
    set_yaw("red_cube", math.radians(yaw_deg))
    x, y, z = sim.object_state("red_cube").position
    tx, ty = x + dx, y + dy
    sim.set_gripper(True)
    sim._move_joints(sim.solve_ik([tx, ty, z + APPROACH_HEIGHT], yaw=grip_yaw))
    sim._move_joints(sim.solve_ik([tx, ty, z + 0.002], yaw=grip_yaw), 0.8)
    sim.set_gripper(False)
    sim._move_joints(sim.solve_ik([tx, ty, z + APPROACH_HEIGHT], yaw=grip_yaw), 0.8)
    held = sim.held_object() == "red_cube"
    # how much did the cube shift relative to the tip while held (affects placement accuracy)
    off = np.linalg.norm(sim.data.xpos[sim.model.body("red_cube").id][:2] - sim.tip_position()[:2]) if held else float("nan")
    others_moved = max(np.hypot(*(np.array(sim.object_state(n).position[:2]) - LAYOUT[n])) for n in ("green_cube", "blue_cube"))
    return held, off, others_moved

print("== cube yaw (default gripper yaw = base pan) ==")
for yd in [0, 10, 20, 30, 40, 45]:
    h, off, _ = trial(yaw_deg=yd)
    print(f"yaw {yd:>3}°  held={h}  cube-tip offset={off*1000:.1f} mm")

print("== grasp target error, along / across radial direction ==")
x, y = LAYOUT["red_cube"]; r = np.array([x, y]) / np.hypot(x, y); t = np.array([-r[1], r[0]])
for name, d in (("radial", r), ("tangential", t)):
    row = []
    for e in [0, 3, 6, 9, 12, 15, 18]:
        res = [trial(dx=s * e / 1000 * d[0], dy=s * e / 1000 * d[1])[0] for s in (1, -1)]
        row.append(f"{e}mm:{''.join('✓' if h else '✗' for h in res)}")
    print(f"{name:<11}", "  ".join(row))
