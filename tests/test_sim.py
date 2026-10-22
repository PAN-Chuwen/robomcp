"""Skills judge their own success from proprioception, not from ground truth."""

from __future__ import annotations

import pytest

from robomcp.sim import SkillError, TabletopSim

LAYOUT = {"red_cube": (0.20, 0.06), "green_cube": (0.24, -0.08), "blue_cube": (0.15, -0.10)}


@pytest.fixture(scope="module")
def sim():
    return TabletopSim()


def test_pick_holds_object_by_gripper_signal(sim):
    sim.reset(LAYOUT)
    assert sim.pick("red_cube") is True
    assert sim.gripper_holding() and sim.held_object() == "red_cube"


def test_closing_on_nothing_is_not_holding(sim):
    sim.reset(LAYOUT)
    sim.move_to(0.20, -0.02, 0.02)
    sim.set_gripper(False)
    assert not sim.gripper_holding()


def test_pick_reports_missed_grasp(sim, monkeypatch):
    sim.reset(LAYOUT)
    real = sim.object_state

    def off_by_3cm(name):  # a perception error well beyond the ~6 mm grasp tolerance
        s = real(name)
        s.position = (s.position[0] + 0.03, s.position[1], s.position[2])
        return s

    monkeypatch.setattr(sim, "object_state", off_by_3cm)
    with pytest.raises(SkillError, match="grasp missed"):
        sim.pick("red_cube")


def test_place_with_empty_gripper_fails_before_moving(sim):
    sim.reset(LAYOUT)
    before = sim.tip_position()
    with pytest.raises(SkillError, match="pick one first"):
        sim.place_in_tray()
    assert (sim.tip_position() == before).all()
