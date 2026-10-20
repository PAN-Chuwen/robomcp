"""MCP server exposing the SO-101 tabletop simulation as robot tools."""

from __future__ import annotations

import random
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage

from robomcp.sim import SkillError, TabletopSim

OUT_DIR = Path(__file__).resolve().parents[2] / "out"

server = MCPServer(
    name="robomcp",
    instructions=(
        "Controls an SO-101 robot arm on a tabletop (MuJoCo simulation). "
        "Coordinates are metres in the robot base frame: +x forward, +y to the robot's left, z up; "
        "the table surface is z=0. Call get_scene before acting and again after each skill to verify "
        "the result. Prefer pick + place_in_tray over raw move_to."
    ),
)
sim = TabletopSim()
# Tools are async on purpose: they then run on the event-loop (main) thread, which owns
# MuJoCo's OpenGL context. Sync tools would run in worker threads and rendering would hang.


def _result(ok: bool, message: str) -> dict:
    return {"ok": ok, "message": message, "scene": sim.scene()}


def _run(fn, *args) -> dict:
    sim.settle_pending()
    try:
        out = fn(*args)
    except SkillError as e:
        return _result(False, str(e))
    return _result(out is not False, "done" if out is not False else "skill finished but the check failed")


@server.tool()
async def get_scene() -> dict:
    """Object positions, whether each object is in the tray, its horizontal distance to the tray, tray position, and gripper state."""
    sim.settle_pending()
    return sim.scene()


@server.tool()
async def look(camera: str = "overview") -> Image:
    """Render the scene. camera: 'overview' (angled view) or 'top' (bird's-eye)."""
    sim.settle_pending()
    return Image(data=sim.render_png(None if camera == "overview" else camera), format="png")


@server.tool()
async def pick(object_name: str) -> dict:
    """Grasp an object from the table with a top-down grasp and lift it. Fails if already holding something."""
    return _run(sim.pick, object_name)


@server.tool()
async def place_in_tray() -> dict:
    """Put the held object into the tray and release it."""
    return _run(sim.place_in_tray)


@server.tool()
async def place_at(x: float, y: float) -> dict:
    """Put the held object down on the table at (x, y) and release it."""
    return _run(sim.place, x, y)


@server.tool()
async def move_to(x: float, y: float, z: float) -> dict:
    """Move the gripper tip to (x, y, z), pointing straight down."""
    return _run(sim.move_to, x, y, z)


@server.tool()
async def set_gripper(open: bool) -> dict:
    """Open (true) or close (false) the gripper."""
    return _run(sim.set_gripper, open)


@server.tool()
async def go_home() -> dict:
    """Return the arm to its rest pose."""
    return _run(sim.go_home)


@server.tool()
async def reset_scene(seed: int | None = None) -> dict:
    """Reset the arm and scatter the cubes. With a seed, cube positions are randomized reproducibly."""
    layout = None
    if seed is not None:
        rng = random.Random(seed)
        layout, taken = {}, []
        for name in sim.objects:
            while True:
                x, y = rng.uniform(0.15, 0.27), rng.uniform(-0.12, 0.10)
                if all((x - a) ** 2 + (y - b) ** 2 > 0.05**2 for a, b in taken):
                    break
            taken.append((x, y))
            layout[name] = (x, y)
    sim.reset(layout, seed=seed)
    return _result(True, "scene reset")


@server.tool()
async def start_recording() -> dict:
    """Start recording frames of every subsequent motion."""
    sim.frames.clear()
    sim.record = True
    return {"ok": True}


@server.tool()
async def save_recording(filename: str = "demo.gif") -> dict:
    """Stop recording and save the frames as a GIF under the project's out/ directory."""
    sim.record = False
    if not sim.frames:
        return {"ok": False, "message": "no frames recorded"}
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / Path(filename).name
    frames = [PILImage.fromarray(f).resize((480, 360)) for f in sim.frames]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=40, loop=0)
    return {"ok": True, "path": str(path), "frames": len(frames)}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
