"""Replay a harness trace in the simulator, check every step against the log, and write a viewer page.

    uv run robomcp-agent replay out/traces/20261022-154651-plan.jsonl

The trace (v2) holds every robot call with its result. Replaying runs the same calls in the same order on a
fresh simulator (same seed, same failure injection) and compares each result with the logged one: MuJoCo is
deterministic, so any difference means the run is not reproducible (different MuJoCo version, changed skill
code, or hidden state). The first differing step is reported as the divergence point.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import mujoco
from PIL import Image

import robomcp.server as server
from robomcp.agent.harness import PROJECT_ROOT
from robomcp.agent.tasks import TASKS
from robomcp.sim import TabletopSim

REPLAY_DIR = PROJECT_ROOT / "out" / "replays"
PAGE = Path(__file__).with_name("replay.html")
SKIPPED = {"start_recording", "save_recording"}  # the replayer records frames itself
POSITION_TOL_M = 1e-3  # logged positions are rounded to 0.1 mm; a deterministic replay matches exactly


@dataclass
class Step:
    index: int  # position in the trace's event list
    by: str  # "executor" or "harness"
    name: str
    args: dict
    logged: object
    replayed: object
    drift_m: float = 0.0  # largest object position difference between logged and replayed scene
    mismatches: list[str] = field(default_factory=list)  # discrete differences (ok, in_tray, holding, ...)
    frames: list[int] = field(default_factory=list)  # indices into Replay.frames shown for this step

    @property
    def matches(self) -> bool:
        return self.drift_m <= POSITION_TOL_M and not self.mismatches


@dataclass
class Replay:
    trace: Path
    events: list[dict]
    steps: list[Step]
    frames: list[bytes]  # JPEG
    success: bool | None  # eval check on the replayed scenes, when the goal is a known task

    @property
    def start(self) -> dict:
        return self.events[0]

    @property
    def divergence(self) -> Step | None:
        return next((s for s in self.steps if not s.matches), None)


def load_trace(path: Path) -> list[dict]:
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not events or events[0].get("kind") != "start" or events[0].get("trace_version", 1) < 2:
        raise ValueError(f"{path} predates trace v2 (no tool results logged); rerun the task to replay it")
    return events


def _scene(result: object) -> dict | None:
    if isinstance(result, dict):
        return result["scene"] if "scene" in result else result if "objects" in result else None
    return None


def compare(logged: object, replayed: object) -> tuple[float, list[str]]:
    """Largest object position drift (m) and the discrete fields that differ."""
    mismatches = []
    if isinstance(logged, dict) and isinstance(replayed, dict):
        for key in ("ok", "message"):
            if logged.get(key) != replayed.get(key):
                mismatches.append(f"{key}: {logged.get(key)!r} -> {replayed.get(key)!r}")
    a, b = _scene(logged), _scene(replayed)
    if a is None or b is None:
        return 0.0, mismatches if a is None and b is None else [*mismatches, "scene missing"]
    objs_b = {o["name"]: o for o in b["objects"]}
    drift = 0.0
    for o in a["objects"]:
        r = objs_b.get(o["name"])
        if r is None:
            mismatches.append(f"{o['name']} missing")
            continue
        drift = max(drift, math.dist(o["position"], r["position"]))
        if o["in_tray"] != r["in_tray"]:
            mismatches.append(f"{o['name']}.in_tray: {o['in_tray']} -> {r['in_tray']}")
    if a["gripper"]["holding"] != b["gripper"]["holding"]:
        mismatches.append(f"holding: {a['gripper']['holding']} -> {b['gripper']['holding']}")
    return drift, mismatches


def _jpeg(frame) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, format="JPEG", quality=70)
    return buf.getvalue()


async def replay(path: Path, render: bool = True) -> Replay:
    events = load_trace(path)
    start = events[0]
    if start.get("mujoco") != mujoco.__version__:
        print(f"warning: trace was recorded with MuJoCo {start.get('mujoco')}, replaying with {mujoco.__version__}")
    # The server's tools use its module-level `sim`; swap in a fresh one so the replay starts from scratch.
    sim = server.sim = TabletopSim(record=render, render_size=(400, 300))
    sim._live_dir = None  # never pace to wall-clock time or write live frames during a replay
    sim.slip, sim.slip_mode = float(start.get("slip") or 0), start.get("slip_mode", "immediate")

    steps, frames = [], []
    for i, e in enumerate(events):
        if e["kind"] not in ("tool", "harness_call") or e["name"] in SKIPPED:
            continue
        out = await getattr(server, e["name"])(**e["args"])
        replayed = json.loads(json.dumps(out))  # tuples -> lists, like the logged JSON
        step = Step(i, "executor" if e["kind"] == "tool" else "harness", e["name"], e["args"], e.get("result"),
                    replayed)
        step.drift_m, step.mismatches = compare(step.logged, replayed)
        if render:
            shot = sim.frames[::2] + [sim.render()]  # 12.5 fps of motion, then the scene after the call
            sim.frames.clear()
            step.frames = list(range(len(frames), len(frames) + len(shot)))
            frames += [_jpeg(f) for f in shot]
        steps.append(step)

    scenes = [_scene(s.replayed) for s in steps if s.name == "get_scene" and s.by == "harness"]
    task = next((t for t in TASKS if t.goal == start["goal"]), None)
    success = task.check(scenes[0], scenes[-1]) if task and len(scenes) >= 2 else None
    return Replay(path, events, steps, frames, success)


def write_viewer(rep: Replay, out_dir: Path | None = None) -> Path:
    """A static page (open it from disk): frames on the left, the run's timeline with replay checks on the right."""
    out_dir = out_dir or REPLAY_DIR / rep.trace.stem
    (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(rep.frames):
        (out_dir / "frames" / f"{i:05d}.jpg").write_bytes(data)
    by_index = {s.index: s for s in rep.steps}
    timeline = []
    for i, e in enumerate(rep.events):
        item = {k: v for k, v in e.items() if k != "result"}
        if s := by_index.get(i):
            item.update(by=s.by, frames=s.frames, matches=s.matches, drift_mm=round(s.drift_m * 1000, 2),
                        mismatches=s.mismatches, scene=_scene(s.replayed))
        timeline.append(item)
    data = {"trace": rep.trace.name, "frames": len(rep.frames), "success": rep.success, "timeline": timeline,
            "divergence": rep.divergence.index if rep.divergence else None}
    page = PAGE.read_text().replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    (out_dir / "index.html").write_text(page)
    return out_dir / "index.html"


def report(rep: Replay) -> None:
    s = rep.start
    print(f"{rep.trace.name}  mode={s['mode']} seed={s.get('seed')} slip={s.get('slip')} {s.get('slip_mode')}")
    print(f"goal: {s['goal']}\n")
    for st in rep.steps:
        mark = "✓" if st.matches else "✗"
        detail = "" if st.matches else f"  drift {st.drift_m * 1000:.1f} mm  {'; '.join(st.mismatches)}"
        print(f"  {mark} {st.by:<9}{st.name}({json.dumps(st.args, ensure_ascii=False)}){detail}")
    div = rep.divergence
    same = sum(st.matches for st in rep.steps)
    print(f"\n{same}/{len(rep.steps)} steps reproduce the log"
          + (f"; first divergence at {div.name} (event {div.index})" if div else ""))
    verdicts = [e["verdict"].get("passed") for e in rep.events if e["kind"] == "verify"]
    if rep.success is not None:
        print(f"eval check on replayed scene: {'success' if rep.success else 'failure'}"
              + (f"; last verifier verdict: {'passed' if verdicts[-1] else 'failed'}" if verdicts else ""))
