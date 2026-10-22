"""Experiment aggregates: success count over scored episodes, with a Wilson 95% interval.

Scored episodes are those that ran to the end (`succeeded` or `failed`). `error` episodes produced no
result and are reported separately rather than counted as failures, so infrastructure trouble does not
masquerade as agent failure.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from robomcp_platform.models import EPISODE_STATUSES, Episode
from robomcp_platform.stats import wilson_interval


@dataclass
class Tally:
    episodes: int = 0
    by_status: dict[str, int] = field(default_factory=lambda: dict.fromkeys(EPISODE_STATUSES, 0))

    @property
    def successes(self) -> int:
        return self.by_status["succeeded"]

    @property
    def scored(self) -> int:
        return self.by_status["succeeded"] + self.by_status["failed"]

    @property
    def success_rate(self) -> float | None:
        return self.successes / self.scored if self.scored else None

    @property
    def wilson_95(self) -> tuple[float, float]:
        return wilson_interval(self.successes, self.scored)

    def as_dict(self) -> dict:
        return {
            "episodes": self.episodes,
            "by_status": dict(self.by_status),
            "successes": self.successes,
            "scored": self.scored,
            "success_rate": self.success_rate,
            "wilson_95": list(self.wilson_95),
        }


def summarize(session: Session, experiment_id: uuid.UUID) -> dict:
    rows = session.execute(
        select(Episode.task_key, Episode.status, func.count())
        .where(Episode.experiment_id == experiment_id)
        .group_by(Episode.task_key, Episode.status)
    ).all()
    overall, per_task = Tally(), defaultdict(Tally)
    for task_key, status, count in rows:
        for tally in (overall, per_task[task_key]):
            tally.episodes += count
            tally.by_status[status] += count
    return {
        **overall.as_dict(),
        "per_task": [{"task_key": k, **per_task[k].as_dict()} for k in sorted(per_task)],
    }
