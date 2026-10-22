"""Claims share workers fairly across orgs instead of draining one org's backlog first."""

from __future__ import annotations

from fakes import TASKS

from robomcp_platform import queue


def _claim(sm, cap=None):
    with sm.begin() as s:
        return queue.claim_next(s, "w", cap)


def test_a_later_org_is_not_starved_by_an_earlier_backlog(make_org, sm):
    big, small = make_org(), make_org()
    big.experiment(TASKS, seeds=list(range(5)))  # 10 episodes queued first
    small.experiment([TASKS[0]], seeds=[1, 2])  # 2 episodes queued after
    order = [_claim(sm).org_id for _ in range(4)]  # claims stay running: each one shifts the fair share
    assert order == [big.org_id, small.org_id, big.org_id, small.org_id]


def test_earlier_experiments_first_within_an_org(make_org, sm):
    # Episodes of one experiment share created_at (one insert), so their order is arbitrary; across
    # experiments of the same org, the earlier experiment drains first.
    org = make_org()
    first = org.experiment([TASKS[0]], seeds=[1, 2], project="one")
    second = org.experiment([TASKS[0]], seeds=[1, 2], project="two")
    claimed = [str(_claim(sm).experiment_id) for _ in range(4)]
    assert claimed == [first["id"]] * 2 + [second["id"]] * 2


def test_per_org_cap_skips_orgs_at_their_limit(make_org, sm):
    a, b = make_org(), make_org()
    a.experiment(TASKS, seeds=[1, 2])
    b.experiment([TASKS[0]], seeds=[1])
    assert _claim(sm, cap=1).org_id == a.org_id
    assert _claim(sm, cap=1).org_id == b.org_id
    assert _claim(sm, cap=1) is None  # both orgs are at their cap; a's other episodes wait
    assert _claim(sm, cap=2).org_id == a.org_id
