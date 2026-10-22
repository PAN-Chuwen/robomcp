"""Probe: top-camera resolution, cube visibility (segmentation) at home and while hovering, depth rendering.

    uv run python scripts/probe_camera.py   # images under out/probes/
"""
import math
from pathlib import Path

import mujoco
from PIL import Image
from robomcp.sim import TabletopSim, APPROACH_HEIGHT

OUT = Path("out/probes")
OUT.mkdir(parents=True, exist_ok=True)
sim = TabletopSim(); m = sim.model
LAYOUT = {"red_cube": (0.20, 0.06), "green_cube": (0.24, -0.08), "blue_cube": (0.15, -0.10)}
cam = m.camera("top"); fovy = m.cam_fovy[cam.id]; H, W = 480, 640
print(f"top cam fovy={fovy}°, height 0.75 m -> {2*0.75*math.tan(math.radians(fovy/2))/H*1000:.2f} mm/px at {W}x{H}")
r = mujoco.Renderer(m, H, W)
def visible(tag):
    r.update_scene(sim.data, camera="top"); r.enable_segmentation_rendering(); seg = r.render(); r.disable_segmentation_rendering()
    counts = {n: int(((seg[..., 0] == m.geom(n).id) & (seg[..., 1] == mujoco.mjtObj.mjOBJ_GEOM)).sum()) for n in LAYOUT}
    print(f"{tag:<26}", "  ".join(f"{k}={v}px" for k, v in counts.items()))
    return seg
sim.reset(LAYOUT); visible("home")
Image.fromarray(sim.render("top")).save(OUT / "top_home.png")
x, y, z = sim.object_state("red_cube").position
sim.move_to(x, y, z + APPROACH_HEIGHT); visible("hover over red")
Image.fromarray(sim.render("top")).save(OUT / "top_hover.png")
r.enable_depth_rendering(); r.update_scene(sim.data, camera="top"); d = r.render(); r.disable_depth_rendering()
print("depth ok, range", float(d.min()), float(d.max()))
