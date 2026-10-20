"""MuJoCo tabletop simulation of an SO-101 arm with pick/place skills."""

from __future__ import annotations

import io
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import mink
import mujoco
import numpy as np
from PIL import Image

MODEL_DIR = Path(__file__).parent / "model"
ARM_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
GRIPPER_OPEN = 1.2
GRIPPER_CLOSED = -0.17
HOME_Q = np.array([0.0, -1.2, 1.1, 1.3, 0.0])
APPROACH_HEIGHT = 0.07  # hover height above a target before descending
TRAY_NAME = "tray"


@dataclass
class ObjectState:
    name: str
    position: tuple[float, float, float]
    in_tray: bool
    lifted: bool


class SkillError(RuntimeError):
    """A skill could not be executed (unreachable target, unknown object, ...)."""


class TabletopSim:
    def __init__(self, record: bool = False, render_size: tuple[int, int] = (640, 480)):
        self.model = mujoco.MjModel.from_xml_path(str(MODEL_DIR / "scene.xml"))
        self.data = mujoco.MjData(self.model)
        self._ik_model = mujoco.MjModel.from_xml_path(str(MODEL_DIR / "so101.xml"))
        self._ik_config = mink.Configuration(self._ik_model)
        self._ik_limits = [mink.ConfigurationLimit(self._ik_model)]
        self._site = "gripperframe"
        self._arm_qadr = [self.model.joint(j).qposadr[0] for j in ARM_JOINTS]
        self._grip_qadr = self.model.joint("gripper").qposadr[0]
        self.objects = [
            self.model.body(i).name for i in range(self.model.nbody) if self.model.body(i).name.endswith("_cube")
        ]
        self.record = record
        self.frames: list[np.ndarray] = []
        # Live view: when ROBOMCP_LIVE_DIR is set, the latest frame is written there as frame.jpg for the web console.
        live = os.environ.get("ROBOMCP_LIVE_DIR")
        self._live_dir = Path(live) if live else None
        self._last_live = 0.0
        self._pace_wall = self._pace_sim = 0.0  # anchors for real-time playback in live mode
        # Failure injection: probability that a placed object bounces out of the tray while the skill still
        # reports success (a silent failure, like an unreliable success signal on a real robot).
        self.slip = float(os.environ.get("ROBOMCP_SLIP", "0") or 0)
        self._rng = random.Random(0)
        self._renderer = mujoco.Renderer(self.model, height=render_size[1], width=render_size[0])
        self._cam = mujoco.MjvCamera()
        self._cam.lookat[:] = [0.18, 0.05, 0.04]
        self._cam.distance, self._cam.azimuth, self._cam.elevation = 0.55, 210, -30
        self.reset()

    # ------------------------------------------------------------------ state

    def reset(self, layout: dict[str, tuple[float, float]] | None = None, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[self._arm_qadr] = HOME_Q
        self.data.qpos[self._grip_qadr] = GRIPPER_OPEN
        self.data.ctrl[:5] = HOME_Q
        self.data.ctrl[5] = GRIPPER_OPEN
        for name, (x, y) in (layout or {}).items():
            adr = self.model.joint(self.model.body(name).jntadr[0]).qposadr[0]
            self.data.qpos[adr : adr + 7] = [x, y, 0.012, 1, 0, 0, 0]
        mujoco.mj_forward(self.model, self.data)
        self.frames.clear()
        self._settle(100)

    def object_state(self, name: str) -> ObjectState:
        if name not in self.objects:
            raise SkillError(f"unknown object '{name}', known: {self.objects}")
        p = self.data.xpos[self.model.body(name).id].copy()
        tray = self.data.xpos[self.model.body(TRAY_NAME).id]
        in_tray = bool(abs(p[0] - tray[0]) < 0.038 and abs(p[1] - tray[1]) < 0.038 and p[2] < 0.04)
        return ObjectState(name, tuple(round(float(v), 4) for v in p), in_tray, bool(p[2] > 0.03 and not in_tray))

    def scene(self) -> dict:
        tray = self.data.xpos[self.model.body(TRAY_NAME).id]
        objects = [vars(self.object_state(n)) for n in self.objects]
        # Derived relation computed in code: models misjudge distances when comparing raw coordinates.
        for o in objects:
            o["distance_to_tray_m"] = round(float(np.hypot(o["position"][0] - tray[0], o["position"][1] - tray[1])), 3)
        return {
            "objects": objects,
            "tray": {"position": tuple(round(float(v), 4) for v in tray), "size_m": 0.08},
            "gripper": {
                "position": tuple(round(float(v), 4) for v in self.tip_position()),
                "opening": round(float(self.data.qpos[self._grip_qadr]), 3),
                "holding": self.held_object(),
            },
        }

    def tip_position(self) -> np.ndarray:
        return self.data.site_xpos[self.model.site(self._site).id].copy()

    def held_object(self) -> str | None:
        tip = self.tip_position()
        for n in self.objects:
            p = self.data.xpos[self.model.body(n).id]
            if np.linalg.norm(p - tip) < 0.03 and p[2] > 0.025:
                return n
        return None

    # ------------------------------------------------------------- kinematics

    def solve_ik(self, position, yaw: float | None = None, iters: int = 300) -> np.ndarray:
        """Joint angles that put the gripper tip at `position`, pointing straight down."""
        position = np.asarray(position, dtype=float)
        theta = np.arctan2(position[1], position[0]) if yaw is None else yaw
        x_axis = np.array([0.0, 0.0, -1.0])
        y_axis = np.array([-np.sin(theta), np.cos(theta), 0.0])
        rot = np.column_stack([x_axis, y_axis, np.cross(x_axis, y_axis)])
        target = mink.SE3.from_rotation_and_translation(mink.SO3.from_matrix(rot), position)

        q = np.zeros(self._ik_model.nq)
        q[:5] = self.data.qpos[self._arm_qadr]
        self._ik_config.update(q)
        task = mink.FrameTask(self._site, "site", position_cost=1.0, orientation_cost=0.2)
        task.set_target(target)
        posture = mink.PostureTask(self._ik_model, cost=1e-3)
        posture.set_target(np.r_[HOME_Q, GRIPPER_OPEN])
        dt = 0.02
        for _ in range(iters):
            vel = mink.solve_ik(self._ik_config, [task, posture], dt, "daqp", damping=1e-3, limits=self._ik_limits)
            self._ik_config.integrate_inplace(vel, dt)
            err = task.compute_error(self._ik_config)
            if np.linalg.norm(err[:3]) < 2e-3 and np.linalg.norm(err[3:]) < 0.05:
                break
        pos_err = float(np.linalg.norm(task.compute_error(self._ik_config)[:3]))
        if pos_err > 0.01:
            raise SkillError(f"target {np.round(position, 3).tolist()} is out of reach (IK error {pos_err * 100:.1f} cm)")
        return self._ik_config.q[:5].copy()

    # ----------------------------------------------------------------- motion

    def _settle(self, steps: int) -> None:
        for i in range(steps):
            mujoco.mj_step(self.model, self.data)
            self._on_step(i)

    def _on_step(self, i: int) -> None:
        if self.record and i % 8 == 0:
            self.frames.append(self.render())
        if self._live_dir:
            self._pace()
            if time.monotonic() - self._last_live > 0.04:
                self.write_live_frame()

    def _pace(self) -> None:
        """Live mode only: keep simulated time in step with wall-clock time so motion plays smoothly."""
        now = time.monotonic()
        if now - self._pace_wall > 0.5:  # idle gap (agent was thinking): re-anchor instead of fast-forwarding
            self._pace_wall, self._pace_sim = now, self.data.time
            return
        ahead = (self.data.time - self._pace_sim) - (now - self._pace_wall)
        if ahead > 0:
            time.sleep(ahead)

    def write_live_frame(self) -> None:
        self._last_live = time.monotonic()
        self._live_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._live_dir / "frame.tmp.jpg"
        Image.fromarray(self.render()).save(tmp, quality=80)
        tmp.replace(self._live_dir / "frame.jpg")  # atomic swap so the browser never sees a half-written file

    def _move_joints(self, q_target: np.ndarray, duration: float = 1.0) -> None:
        q_start = self.data.ctrl[:5].copy()
        n = max(int(duration / self.model.opt.timestep), 1)
        for i in range(1, n + 1):
            s = i / n
            s = s * s * (3 - 2 * s)  # smoothstep
            self.data.ctrl[:5] = q_start + s * (q_target - q_start)
            mujoco.mj_step(self.model, self.data)
            self._on_step(i)
        self._settle(60)

    def move_to(self, x: float, y: float, z: float, duration: float = 1.0) -> None:
        self._move_joints(self.solve_ik([x, y, z]), duration)

    def set_gripper(self, open_: bool) -> None:
        self.data.ctrl[5] = GRIPPER_OPEN if open_ else GRIPPER_CLOSED
        self._settle(120)

    def go_home(self) -> None:
        self._move_joints(HOME_Q, 1.2)

    # ----------------------------------------------------------------- skills

    def pick(self, name: str) -> bool:
        state = self.object_state(name)
        if state.in_tray:
            raise SkillError(f"{name} is already in the tray")
        held = self.held_object()
        if held:
            raise SkillError(f"gripper is already holding {held}; place it first")
        x, y, z = state.position
        self.set_gripper(True)
        self.move_to(x, y, z + APPROACH_HEIGHT)
        self.move_to(x, y, z + 0.002, duration=0.8)
        self.set_gripper(False)
        self.move_to(x, y, z + APPROACH_HEIGHT, duration=0.8)
        return self.held_object() == name

    def place(self, x: float, y: float) -> None:
        held = self.held_object()
        self.move_to(x, y, 0.012 + APPROACH_HEIGHT)
        self.move_to(x, y, 0.035, duration=0.8)
        self.set_gripper(True)
        self.move_to(x, y, 0.012 + APPROACH_HEIGHT, duration=0.6)
        if held is None:
            raise SkillError("place executed with an empty gripper")
        if self.slip and self._rng.random() < self.slip:
            self._bounce_out(held)

    def _bounce_out(self, name: str) -> None:
        """Silent failure: move the just-placed object off the tray; the caller is not told."""
        tray = self.data.xpos[self.model.body(TRAY_NAME).id]
        adr = self.model.joint(self.model.body(name).jntadr[0]).qposadr[0]
        self.data.qpos[adr : adr + 7] = [tray[0] + 0.07, tray[1] - 0.02, 0.012, 1, 0, 0, 0]
        self.data.qvel[self.model.joint(self.model.body(name).jntadr[0]).dofadr[0] : ][:6] = 0
        mujoco.mj_forward(self.model, self.data)
        self._settle(60)

    def place_in_tray(self) -> None:
        tray = self.data.xpos[self.model.body(TRAY_NAME).id]
        self.place(float(tray[0]), float(tray[1]))

    # ---------------------------------------------------------------- render

    def render(self, camera: str | None = None) -> np.ndarray:
        self._renderer.update_scene(self.data, camera=camera if camera else self._cam)
        return self._renderer.render()

    def render_png(self, camera: str | None = None) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(self.render(camera)).save(buf, format="PNG")
        return buf.getvalue()
