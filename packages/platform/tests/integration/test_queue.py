import threading
import time
import uuid
from collections import Counter

import pytest
from fakes import FakeRunner, RaisingRunner
from sqlalchemy import select, text

from robomcp_platform import queue
from robomcp_platform.models import Episode, Experiment
from robomcp_platform.runner import EpisodeResult
from robomcp_platform.worker import Worker

ONE_TASK = [{"key": "t"}]


def _episode(sm, episode_id) -> Episode:
    with sm() as s:
        return s.get_one(Episode, episode_id)


def _experiment(sm, experiment_id) -> Experiment:
    with sm() as s:
        return s.get_one(Experiment, uuid.UUID(experiment_id))


def _claim(sm, worker_id):
    with sm.begin() as s:
        return queue.claim_next(s, worker_id)


def _make_stale(sm, episode_id, seconds=3600):
    with sm.begin() as s:
        s.execute(text("UPDATE episodes SET heartbeat_at = now() - make_interval(secs => :n) WHERE id = :id"),
                  {"n": seconds, "id": episode_id})


def _reap(sm, max_attempts=3, timeout=30.0):
    with sm.begin() as s:
        return queue.reap_stale(s, timeout, max_attempts)


def test_concurrent_claims_never_hand_out_the_same_episode(make_org, sm):
    org = make_org()
    org.experiment([{"key": f"t{i}"} for i in range(10)], seeds=list(range(20)))  # 200 episodes
    n_workers, start = 12, threading.Barrier(12)
    claims: dict[str, list[uuid.UUID]] = {f"w{i}": [] for i in range(n_workers)}
    errors: list[BaseException] = []

    def work(worker_id: str) -> None:
        try:
            start.wait()
            while (spec := _claim(sm, worker_id)) is not None:
                claims[worker_id].append(spec.episode_id)
        except BaseException as exc:  # surface thread failures in the main thread
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(w,)) for w in claims]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors
    all_claims = [e for ids in claims.values() for e in ids]
    duplicates = [e for e, n in Counter(all_claims).items() if n > 1]
    assert not duplicates
    assert len(all_claims) == 200
    assert sum(1 for ids in claims.values() if ids) > 1  # the claims really were spread over workers
    with sm() as s:
        rows = s.execute(select(Episode.id, Episode.claimed_by, Episode.status, Episode.attempts)).all()
    owner = {e: w for w, ids in claims.items() for e in ids}
    assert all(r.status == "running" and r.attempts == 1 and owner[r.id] == r.claimed_by for r in rows)


def test_claim_skips_rows_locked_by_an_open_transaction(make_org, sm):
    org = make_org()
    org.experiment(ONE_TASK, seeds=[1, 2])
    with sm.begin() as holding:  # first claim's transaction stays open while others try
        first = queue.claim_next(holding, "w1")
        second = _claim(sm, "w2")
        third = _claim(sm, "w3")
        assert first is not None and second is not None
        assert first.episode_id != second.episode_id
        assert third is None  # the only other row is locked by the open transaction, not waited on


def test_stale_heartbeat_is_requeued_and_claimed_again(make_org, sm):
    org = make_org()
    exp = org.experiment(ONE_TASK, seeds=[1])
    spec = _claim(sm, "dead-worker")
    assert _experiment(sm, exp["id"]).status == "running"

    assert _reap(sm) == []  # fresh heartbeat: left alone
    _make_stale(sm, spec.episode_id)
    reaped = _reap(sm)
    assert [(r.episode_id, r.status) for r in reaped] == [(spec.episode_id, "queued")]
    ep = _episode(sm, spec.episode_id)
    assert (ep.status, ep.claimed_by, ep.heartbeat_at, ep.attempts) == ("queued", None, None, 1)
    assert "heartbeat lost" in ep.error

    # The dead worker can no longer heartbeat or report; the next claimer owns it.
    with sm.begin() as s:
        assert queue.heartbeat(s, spec.episode_id, "dead-worker") is False
    again = _claim(sm, "w2")
    assert again.episode_id == spec.episode_id and again.attempt == 2
    with sm.begin() as s:
        assert queue.complete(s, spec.episode_id, "dead-worker", EpisodeResult(success=True)) is False
    with sm.begin() as s:
        assert queue.complete(s, spec.episode_id, "w2", EpisodeResult(success=False)) is True
    ep = _episode(sm, spec.episode_id)
    assert (ep.status, ep.success, ep.claimed_by, ep.error) == ("failed", False, "w2", None)
    assert _experiment(sm, exp["id"]).status == "completed"


def test_stale_episode_errors_after_max_attempts(make_org, sm):
    org = make_org()
    exp = org.experiment(ONE_TASK, seeds=[1])
    statuses = []
    for attempt in (1, 2):
        spec = _claim(sm, f"w{attempt}")
        assert spec.attempt == attempt
        _make_stale(sm, spec.episode_id)
        statuses += [r.status for r in _reap(sm, max_attempts=2)]
    assert statuses == ["queued", "error"]

    ep = _episode(sm, spec.episode_id)
    assert (ep.status, ep.attempts, ep.claimed_by) == ("error", 2, "w2")
    assert ep.finished_at is not None and "attempt 2" in ep.error
    assert _claim(sm, "w3") is None  # errored episodes are not handed out again
    experiment = _experiment(sm, exp["id"])
    assert experiment.status == "completed" and experiment.finished_at is not None

    summary = org.ok("GET", f"/v1/experiments/{exp['id']}")["results"]
    assert summary["by_status"]["error"] == 1 and summary["scored"] == 0  # errors are not agent failures


def test_reaper_only_touches_stale_rows(make_org, sm):
    org = make_org()
    org.experiment(ONE_TASK, seeds=[1, 2, 3])
    stale, fresh = _claim(sm, "a"), _claim(sm, "b")
    _make_stale(sm, stale.episode_id)
    assert [r.episode_id for r in _reap(sm)] == [stale.episode_id]
    assert _episode(sm, fresh.episode_id).status == "running"


def test_runner_exception_retries_then_errors(make_org, sm, settings):
    org = make_org()
    exp = org.experiment(ONE_TASK, seeds=[1])
    runner = RaisingRunner(ValueError("bad scene"))
    worker = Worker(sm, runner, settings.model_copy(update={"max_attempts": 2}), worker_id="w")

    assert worker.run_once() is True
    ep = _episode(sm, uuid.UUID(org.ok("GET", f"/v1/experiments/{exp['id']}/episodes")["items"][0]["id"]))
    assert (ep.status, ep.attempts, ep.claimed_by) == ("queued", 1, None)
    assert "ValueError: bad scene" in ep.error

    assert worker.run_once() is True
    assert worker.run_once() is False
    ep = _episode(sm, ep.id)
    assert (ep.status, ep.attempts) == ("error", 2) and runner.calls == 2
    assert _experiment(sm, exp["id"]).status == "completed"


def test_worker_heartbeats_keep_a_long_episode_alive(make_org, sm, settings):
    """heartbeat every 0.1 s, timeout 0.5 s: an episode running 1.2 s must survive a reap mid-run."""
    org = make_org()
    org.experiment(ONE_TASK, seeds=[1])
    reaped_mid_run = []

    def stall_then_reap(spec):
        time.sleep(1.2)
        reaped_mid_run.extend(_reap(sm, timeout=settings.heartbeat_timeout_s))

    worker = Worker(sm, FakeRunner(decide=lambda s: True, before_return=stall_then_reap), settings, "w")
    assert worker.run_once() is True
    assert reaped_mid_run == []
    with sm() as s:
        assert s.scalars(select(Episode.status)).one() == "succeeded"


def test_two_workers_finishing_last_episodes_complete_the_experiment(make_org, sm):
    org = make_org()
    exp = org.experiment(ONE_TASK, seeds=[1, 2])
    a, b = _claim(sm, "a"), _claim(sm, "b")
    start = threading.Barrier(2)

    def finish(spec, worker_id):
        start.wait()
        with sm.begin() as s:
            queue.complete(s, spec.episode_id, worker_id, EpisodeResult(success=True))

    threads = [threading.Thread(target=finish, args=args) for args in ((a, "a"), (b, "b"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert _experiment(sm, exp["id"]).status == "completed"


@pytest.mark.parametrize("bad", ["no_colon", "robomcp_platform.runner:EpisodeSpec"])
def test_load_runner_rejects_bad_paths(bad):
    from robomcp_platform.worker import load_runner

    with pytest.raises((ValueError, TypeError)):
        load_runner(bad)


def test_default_runner_is_the_unimplemented_harness_stub(settings):
    from robomcp_platform.worker import load_runner

    runner = load_runner(settings.worker_runner)
    with pytest.raises(NotImplementedError):
        runner.run(None)  # type: ignore[arg-type]
