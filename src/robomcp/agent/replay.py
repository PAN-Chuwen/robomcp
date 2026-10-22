"""Replay a harness trace in the simulator, check every step against the log, and write a viewer page.

    uv run robomcp-agent replay out/traces/20261022-154651-plan.jsonl

A run is two files: the trace (agent side: plan, tool calls, verdicts) and the environment's episode log
(<run>.env.jsonl: every robot call with what the agent saw and the ground truth). Replaying runs the logged
calls in the same order on a fresh simulator (same seed, same failure injection) and compares both the
observation and the truth with the log: MuJoCo is deterministic, so any difference means the run is not
reproducible (different MuJoCo version, changed skill code, or hidden state). The first differing step is
reported as the divergence point.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

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
    index: int  # step number in the episode log
    name: str
    args: dict
    logged: dict  # the episode-log record: observation + truth
    observation: object = None  # replayed
    truth: dict | None = None  # replayed
    drift_m: float = 0.0  # largest object position difference, over observation and truth
    mismatches: list[str] = field(default_factory=list)  # discrete differences (ok, in_tray, holding, ...)
    frames: list[int] = field(default_factory=list)  # indices into Replay.frames shown for this step

    @property
    def matches(self) -> bool:
        return self.drift_m <= POSITION_TOL_M and not self.mismatches


@dataclass
class Replay:
    trace: Path
    events: list[dict]  # the trace (agent side)
    episode: dict  # the episode log header (slip, perception, MuJoCo version)
    steps: list[Step]
    frames: list[bytes]  # JPEG
    success: bool | None  # eval check on the replayed scenes, when the goal is a known task

    @property
    def start(self) -> dict:
        return self.events[0]

    @property
    def divergence(self) -> Step | None:
        return next((s for s in self.steps if not s.matches), None)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_run(path: Path) -> tuple[list[dict], dict, list[dict]]:
    """Trace events, episode-log header, episode-log steps."""
    events = _jsonl(path)
    if not events or events[0].get("kind") != "start" or events[0].get("trace_version", 1) < 3:
        raise ValueError(f"{path} predates trace v3 (no episode log); rerun the task to replay it")
    log = _jsonl(path.with_name(events[0]["episode_log"]))
    return events, log[0], [r for r in log if r["kind"] == "step"]


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
    events, episode, logged = load_run(path)
    recorded, current = episode.get("fingerprint", {}), server.environment_fingerprint()
    changed = [k for k in current if recorded.get(k) != current[k]]
    if not recorded:
        print("warning: episode log has no environment fingerprint; a divergence cannot be explained")
    elif changed:  # a divergence is then expected; say why up front
        print(f"warning: environment changed since recording ({', '.join(changed)}); steps may diverge")
    # The server's tools use its module-level `sim`; swap in a fresh one so the replay starts from scratch, and
    # detach the episode log so the replay does not overwrite the record it is checked against.
    sim = server.sim = TabletopSim(record=render, render_size=(400, 300))
    server.episode = None
    sim._live_dir = None  # never pace to wall-clock time or write live frames during a replay
    sim.slip, sim.slip_mode = float(episode.get("slip") or 0), episode.get("slip_mode", "immediate")

    steps, frames = [], []
    for rec in logged:
        step = Step(rec["step"], rec["tool"], rec["args"], rec)
        if rec["tool"] not in SKIPPED:
            out = await getattr(server, rec["tool"])(**rec["args"])
            step.observation = json.loads(json.dumps(out)) if isinstance(out, dict) else f"<{type(out).__name__}>"
            step.truth = json.loads(json.dumps(sim.truth()))  # tuples -> lists, like the logged JSON
            d_obs, m_obs = compare(rec["observation"], step.observation)
            d_truth, m_truth = compare(rec["truth"], step.truth)
            step.drift_m = max(d_obs, d_truth)
            step.mismatches = [f"observed {m}" for m in m_obs] + [f"true {m}" for m in m_truth]
        if render:
            shot = sim.frames[::2] + [sim.render()]  # 12.5 fps of motion, then the scene after the call
            sim.frames.clear()
            step.frames = list(range(len(frames), len(frames) + len(shot)))
            frames += [_jpeg(f) for f in shot]
        steps.append(step)

    scored = next((e for e in events if e["kind"] == "scored_steps"), None)
    task = next((t for t in TASKS if t.goal == events[0]["goal"]), None)
    success = None
    if task and scored and max(scored["before"], scored["after"]) < len(steps):
        success = task.check(steps[scored["before"]].truth, steps[scored["after"]].truth)
    return Replay(path, events, episode, steps, frames, success)


def write_viewer(rep: Replay, out_dir: Path | None = None) -> Path:
    """A static page (open it from disk): frames on the left, the run's timeline with replay checks on the right."""
    out_dir = out_dir or REPLAY_DIR / rep.trace.stem
    (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    for i, data in enumerate(rep.frames):
        (out_dir / "frames" / f"{i:05d}.jpg").write_bytes(data)
    by_step = {s.index: s for s in rep.steps}
    timeline = []
    for e in rep.events:
        item = dict(e)
        if (s := by_step.get(e.get("step", -1))) is not None:
            item.update(by="executor" if e["kind"] == "tool" else "harness", frames=s.frames, matches=s.matches,
                        drift_mm=round(s.drift_m * 1000, 2), mismatches=s.mismatches, scene=s.truth)
        timeline.append(item)
    div = rep.divergence
    data = {"trace": rep.trace.name, "frames": len(rep.frames), "success": rep.success, "timeline": timeline,
            "episode": rep.episode,
            "divergence": next((i for i, e in enumerate(rep.events) if div and e.get("step") == div.index), None)}
    page = PAGE.read_text().replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    (out_dir / "index.html").write_text(page)
    return out_dir / "index.html"


def report(rep: Replay) -> None:
    s = rep.start
    print(f"{rep.trace.name}  mode={s['mode']} seed={s.get('seed')} slip={s.get('slip')} {s.get('slip_mode')}")
    print(f"goal: {s['goal']}\n")
    by = {e["step"]: "executor" if e["kind"] == "tool" else "harness" for e in rep.events if "step" in e}
    for st in rep.steps:
        mark = "✓" if st.matches else "✗"
        detail = "" if st.matches else f"  drift {st.drift_m * 1000:.1f} mm  {'; '.join(st.mismatches)}"
        print(f"  {mark} {st.index:>3} {by.get(st.index, '?'):<9}{st.name}({json.dumps(st.args, ensure_ascii=False)}){detail}")
    div = rep.divergence
    same = sum(st.matches for st in rep.steps)
    print(f"\n{same}/{len(rep.steps)} steps reproduce the episode log"
          + (f"; first divergence at step {div.index} {div.name}" if div else ""))
    verdicts = [e["verdict"].get("passed") for e in rep.events if e["kind"] == "verify"]
    if rep.success is not None:
        print(f"eval check on replayed scene: {'success' if rep.success else 'failure'}"
              + (f"; last verifier verdict: {'passed' if verdicts[-1] else 'failed'}" if verdicts else ""))
