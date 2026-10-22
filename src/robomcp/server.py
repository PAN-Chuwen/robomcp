"""MCP server exposing the SO-101 tabletop simulation as robot tools."""

from __future__ import annotations

import functools
import inspect
import json
import os
import random
from pathlib import Path

import mujoco

from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage

from robomcp import safety
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


class EpisodeLog:
    """The environment's own record of an episode: every tool call with what the agent saw and the truth.

    Written by the environment, not the agent, so scoring and replay never depend on the agent's account,
    and an external agent cannot leak or fake ground truth.
    """

    def __init__(self, path: Path) -> None:
        self.path, self.steps = path, 0
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write({"kind": "episode", "slip": sim.slip, "slip_mode": sim.slip_mode,
                     "perception": sim.perception.name, "mujoco": mujoco.__version__}, mode="w")

    def _write(self, record: dict, mode: str = "a") -> None:
        with self.path.open(mode) as f:  # one line per call, flushed, so a crashed episode keeps its steps
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def step(self, tool: str, args: dict, observation: object) -> None:
        if not isinstance(observation, (dict, list, str, int, float, bool, type(None))):
            observation = f"<{type(observation).__name__}>"  # images are not logged
        self._write({"kind": "step", "step": self.steps, "tool": tool, "args": args, "observation": observation,
                     "truth": sim.truth()})
        self.steps += 1


_log_path = os.environ.get("ROBOMCP_EPISODE_LOG")
episode: EpisodeLog | None = EpisodeLog(Path(_log_path)) if _log_path else None


def recorded(fn):
    """Log every call of a tool to the episode log, if one is configured."""
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        out = await fn(*args, **kwargs)
        if episode:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            episode.step(fn.__name__, json.loads(json.dumps(bound.arguments)), json.loads(json.dumps(out))
                         if isinstance(out, dict) else out)
        return out

    return wrapper


def _result(ok: bool, message: str) -> dict:
    return {"ok": ok, "message": message, "scene": sim.observe()}


def _gated(tool: str, args: dict, fn, *fn_args) -> dict:
    """Run a command with free coordinates only if the safety gate allows it."""
    reason = safety.check(tool, args)
    if reason:
        sim.settle_pending()
        return {**_result(False, f"blocked by safety gate: {reason}"), "blocked": True}
    return _run(fn, *fn_args)


def _run(fn, *args) -> dict:
    sim.settle_pending()
    try:
        out = fn(*args)
    except SkillError as e:
        return _result(False, str(e))
    return _result(out is not False, "done" if out is not False else "skill finished but the check failed")


@server.tool()
@recorded
async def get_scene() -> dict:
    """Perceived object positions, whether each object is in the tray, its horizontal distance to the tray, tray position, and gripper state (holding: whether the gripper is closed on something)."""
    sim.settle_pending()
    return sim.observe()


@server.tool()
@recorded
async def look(camera: str = "overview") -> Image:
    """Render the scene. camera: 'overview' (angled view) or 'top' (bird's-eye)."""
    sim.settle_pending()
    return Image(data=sim.render_png(None if camera == "overview" else camera), format="png")


@server.tool()
@recorded
async def pick(object_name: str) -> dict:
    """Grasp an object from the table with a top-down grasp and lift it. Fails if already holding something."""
    return _run(sim.pick, object_name)


@server.tool()
@recorded
async def place_in_tray() -> dict:
    """Put the held object into the tray and release it."""
    return _run(sim.place_in_tray)


@server.tool()
@recorded
async def place_at(x: float, y: float) -> dict:
    """Put the held object down on the table at (x, y) and release it."""
    return _gated("place_at", {"x": x, "y": y}, sim.place, x, y)


@server.tool()
@recorded
async def move_to(x: float, y: float, z: float) -> dict:
    """Move the gripper tip to (x, y, z), pointing straight down."""
    return _gated("move_to", {"x": x, "y": y, "z": z}, sim.move_to, x, y, z)


@server.tool()
@recorded
async def set_gripper(open: bool) -> dict:
    """Open (true) or close (false) the gripper."""
    return _run(sim.set_gripper, open)


@server.tool()
@recorded
async def go_home() -> dict:
    """Return the arm to its rest pose."""
    return _run(sim.go_home)


@server.tool()
@recorded
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
@recorded
async def start_recording() -> dict:
    """Start recording frames of every subsequent motion."""
    sim.frames.clear()
    sim.record = True
    return {"ok": True}


@server.tool()
@recorded
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
