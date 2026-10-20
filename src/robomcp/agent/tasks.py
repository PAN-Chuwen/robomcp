"""Evaluation tasks with automatic success checks computed from the scene state."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


def _objs(scene: dict) -> dict:
    return {o["name"]: o for o in scene["objects"]}


def _moved(before: dict, after: dict, name: str, tol: float = 0.01) -> bool:
    a, b = _objs(before)[name]["position"], _objs(after)[name]["position"]
    return math.dist(a[:2], b[:2]) > tol


def _farthest_from_tray(scene: dict) -> str:
    tray = scene["tray"]["position"]
    return max(scene["objects"], key=lambda o: math.dist(o["position"][:2], tray[:2]))["name"]


@dataclass
class Task:
    key: str
    kind: str  # simple / multi-step / reasoning / trap
    goal: str
    check: Callable[[dict, dict], bool]  # (scene_before, scene_after) -> success


TASKS = [
    Task("red", "simple", "把红色方块放进托盘",
         lambda b, a: _objs(a)["red_cube"]["in_tray"]),
    Task("all", "multi-step", "把桌上所有方块都放进托盘",
         lambda b, a: all(o["in_tray"] for o in a["objects"])),
    Task("green_keep_blue", "multi-step", "把绿色方块放进托盘，不要动蓝色方块",
         lambda b, a: _objs(a)["green_cube"]["in_tray"] and not _moved(b, a, "blue_cube")),
    Task("farthest", "reasoning", "把离托盘最远的那个方块放进托盘，其他方块不要动",
         lambda b, a: _objs(a)[_farthest_from_tray(b)]["in_tray"]
         and not any(_moved(b, a, n) for n in _objs(b) if n != _farthest_from_tray(b))),
    Task("yellow_trap", "trap", "把黄色方块放进托盘",
         lambda b, a: not any(o["in_tray"] for o in a["objects"]) and not any(_moved(b, a, n) for n in _objs(b))),
]
