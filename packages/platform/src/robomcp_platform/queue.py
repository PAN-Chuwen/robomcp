"""Episode job queue in Postgres (no broker).

- Creating an experiment expands tasks x seeds x repeats into `queued` episodes.
- Workers claim with `SELECT ... FOR UPDATE SKIP LOCKED`, so concurrent claimers never get the same row.
- A running episode carries `claimed_by` and `heartbeat_at`; every later write by the worker is guarded by
  `claimed_by = me AND status = 'running'`, so a worker that lost its claim cannot overwrite anything.
- The reaper requeues running episodes whose heartbeat is older than the timeout, or marks them `error`
  once they have used `max_attempts` claims.

Functions here do not commit; run each in its own transaction (`with sessionmaker.begin() as s:`).
Lock order is always episode row(s) first, then the experiment row, which rules out deadlocks.
All timestamps come from the database clock (`now()`), never from worker clocks.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, insert, literal, select, text, update
from sqlalchemy.orm import Session

from robomcp_platform.models import TERMINAL_EPISODE_STATUSES, AgentVersion, Episode, Experiment, SuiteVersion
from robomcp_platform.runner import EpisodeResult, EpisodeSpec


def expand_episodes(session: Session, experiment: Experiment, task_keys: list[str]) -> int:
    """Insert one queued episode per (task, seed, repeat). Returns the number inserted."""
    rows = [
        {
            "id": uuid.uuid4(),
            "org_id": experiment.org_id,
            "experiment_id": experiment.id,
            "task_key": key,
            "seed": seed,
            "repeat_index": r,
        }
        for key, seed, r in itertools.product(task_keys, experiment.seeds, range(experiment.repeats))
    ]
    if rows:
        session.execute(insert(Episode), rows)
    return len(rows)


_CLAIM_SQL = text(
    """
    WITH next AS (
        SELECT id FROM episodes
        WHERE status = 'queued'
        ORDER BY created_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE episodes AS e
    SET status = 'running', claimed_by = :worker, attempts = e.attempts + 1,
        heartbeat_at = now(), started_at = now(), finished_at = NULL
    FROM next
    WHERE e.id = next.id
    RETURNING e.id, e.experiment_id
    """
)


def claim_next(session: Session, worker_id: str) -> EpisodeSpec | None:
    """Claim the oldest queued episode for `worker_id`, or return None if the queue is empty."""
    row = session.execute(_CLAIM_SQL, {"worker": worker_id}).one_or_none()
    if row is None:
        return None
    episode_id, experiment_id = row
    # Mark the experiment running without waiting: if another claimer holds the row it is doing the same.
    session.execute(
        update(Experiment)
        .where(Experiment.id.in_(
            select(Experiment.id)
            .where(Experiment.id == experiment_id, Experiment.status == "queued")
            .with_for_update(skip_locked=True)
        ))
        .values(status="running")
    )
    episode, experiment, suite_version, agent_version = session.execute(
        select(Episode, Experiment, SuiteVersion, AgentVersion)
        .join(Experiment, Experiment.id == Episode.experiment_id)
        .join(SuiteVersion, SuiteVersion.id == Experiment.suite_version_id)
        .join(AgentVersion, AgentVersion.id == Experiment.agent_version_id)
        .where(Episode.id == episode_id)
    ).one()
    task = next(t for t in suite_version.tasks if t["key"] == episode.task_key)
    return EpisodeSpec(
        episode_id=episode.id,
        org_id=episode.org_id,
        project_id=experiment.project_id,
        experiment_id=experiment.id,
        suite_version_id=suite_version.id,
        agent_version_id=agent_version.id,
        task_key=episode.task_key,
        task=task,
        agent_config=agent_version.config,
        seed=episode.seed,
        repeat_index=episode.repeat_index,
        attempt=episode.attempts,
    )


def _owned(episode_id: uuid.UUID, worker_id: str):
    return (Episode.id == episode_id, Episode.claimed_by == worker_id, Episode.status == "running")


def heartbeat(session: Session, episode_id: uuid.UUID, worker_id: str) -> bool:
    """Refresh the heartbeat. False means this worker no longer owns the episode."""
    res = session.execute(update(Episode).where(*_owned(episode_id, worker_id)).values(heartbeat_at=func.now()))
    return res.rowcount == 1


def complete(session: Session, episode_id: uuid.UUID, worker_id: str, result: EpisodeResult) -> bool:
    """Record a result. False (and no write) if the claim was lost, e.g. reaped after a stall."""
    res = session.execute(
        update(Episode)
        .where(*_owned(episode_id, worker_id))
        .values(
            status="succeeded" if result.success else "failed",
            success=result.success,
            metrics=result.metrics,
            trace_uri=result.trace_uri,
            episode_log_uri=result.episode_log_uri,
            finished_at=func.now(),
            error=None,
        )
        .returning(Episode.experiment_id)
    ).one_or_none()
    if res is None:
        return False
    _finish_experiment_if_done(session, res[0])
    return True


def fail(session: Session, episode_id: uuid.UUID, worker_id: str, error: str, max_attempts: int) -> str | None:
    """The runner raised: requeue, or mark `error` once attempts are used up. Returns the new status."""
    exhausted = Episode.attempts >= max_attempts
    res = session.execute(
        update(Episode)
        .where(*_owned(episode_id, worker_id))
        .values(_retry_or_error(exhausted, error))
        .returning(Episode.experiment_id, Episode.status)
    ).one_or_none()
    if res is None:
        return None
    if res[1] == "error":
        _finish_experiment_if_done(session, res[0])
    return res[1]


@dataclass(frozen=True)
class Reaped:
    episode_id: uuid.UUID
    experiment_id: uuid.UUID
    status: str  # "queued" (requeued) or "error"


_STALE_SQL = text(
    """
    SELECT id FROM episodes
    WHERE status = 'running' AND heartbeat_at < now() - make_interval(secs => :timeout)
    ORDER BY heartbeat_at
    FOR UPDATE SKIP LOCKED
    """
)


def reap_stale(session: Session, heartbeat_timeout_s: float, max_attempts: int) -> list[Reaped]:
    """Requeue (or error out) running episodes whose heartbeat is older than the timeout."""
    stale_ids = list(session.scalars(_STALE_SQL, {"timeout": heartbeat_timeout_s}))
    if not stale_ids:
        return []
    exhausted = Episode.attempts >= max_attempts
    rows = session.execute(
        update(Episode)
        .where(Episode.id.in_(stale_ids))
        .values(_retry_or_error(exhausted, "heartbeat lost"))
        .returning(Episode.id, Episode.experiment_id, Episode.status)
    ).all()
    for experiment_id in sorted({r.experiment_id for r in rows if r.status == "error"}):
        _finish_experiment_if_done(session, experiment_id)
    return [Reaped(r.id, r.experiment_id, r.status) for r in rows]


def _retry_or_error(exhausted, error: str) -> dict[str, Any]:
    """SET clause shared by `fail` and `reap_stale`; `exhausted` is evaluated on the pre-update row."""

    def pick(if_error, if_retry):
        return case((exhausted, if_error), else_=if_retry)

    return {
        "status": pick(literal("error"), literal("queued")),
        # Keep claimed_by on errored rows for debugging; clear it when the row goes back to the queue.
        "claimed_by": pick(Episode.claimed_by, None),
        "heartbeat_at": None,
        "finished_at": pick(func.now(), None),
        "error": func.concat(error, literal(" (attempt "), Episode.attempts, literal(")")),
    }


def _finish_experiment_if_done(session: Session, experiment_id: uuid.UUID) -> None:
    # Lock the experiment row so two workers finishing the last two episodes serialise here; the second
    # one's count then sees the first one's committed update.
    session.execute(select(Experiment.id).where(Experiment.id == experiment_id).with_for_update())
    open_count = session.scalar(
        select(func.count())
        .select_from(Episode)
        .where(Episode.experiment_id == experiment_id, Episode.status.not_in(TERMINAL_EPISODE_STATUSES))
    )
    if open_count == 0:
        session.execute(
            update(Experiment)
            .where(Experiment.id == experiment_id, Experiment.status != "completed")
            .values(status="completed", finished_at=func.now())
        )
