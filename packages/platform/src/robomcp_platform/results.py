"""Experiment aggregates and paired comparisons.

Per experiment: success count over scored episodes with a Wilson 95% interval, and pass^k when tasks are
repeated on the same seed. Between two experiments: a paired comparison on the same (task, seed, repeat),
tested with exact McNemar, which is what a regression gate should look at.

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
from robomcp_platform.stats import mcnemar_exact_p, pass_hat_k, wilson_interval

SCORED = ("succeeded", "failed")


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
        "pass_k": pass_k(session, experiment_id),
    }


def pass_k(session: Session, experiment_id: uuid.UUID) -> list[dict]:
    """pass^k for k = 1..max repeats, averaged over (task, seed) groups with at least k scored trials."""
    rows = session.execute(
        select(Episode.task_key, Episode.seed, func.count(), func.count().filter(Episode.status == "succeeded"))
        .where(Episode.experiment_id == experiment_id, Episode.status.in_(SCORED))
        .group_by(Episode.task_key, Episode.seed)
    ).all()
    out = []
    for k in range(1, max((n for *_, n, _ in rows), default=0) + 1):
        groups = [pass_hat_k(c, n, k) for _, _, n, c in rows if n >= k]
        out.append({"k": k, "value": sum(groups) / len(groups), "groups": len(groups)})
    return out


def compare(session: Session, baseline: uuid.UUID, candidate: uuid.UUID, alpha: float = 0.05) -> dict:
    """Pair scored episodes on (task, seed, repeat) and test whether the candidate differs from the baseline.

    Pairing removes scene-to-scene variance: only pairs where exactly one side succeeded are evidence.
    """
    def outcomes(experiment_id: uuid.UUID) -> dict[tuple, bool]:
        rows = session.execute(
            select(Episode.task_key, Episode.seed, Episode.repeat_index, Episode.status)
            .where(Episode.experiment_id == experiment_id, Episode.status.in_(SCORED))
        ).all()
        return {(t, s, r): st == "succeeded" for t, s, r, st in rows}

    a, b = outcomes(baseline), outcomes(candidate)
    cells: dict[str, dict[str, int]] = defaultdict(lambda: {"both": 0, "only_baseline": 0, "only_candidate": 0,
                                                            "neither": 0})
    for key in sorted(a.keys() & b.keys()):
        cell = {(True, True): "both", (True, False): "only_baseline", (False, True): "only_candidate",
                (False, False): "neither"}[(a[key], b[key])]
        cells[key[0]][cell] += 1
        cells["*"][cell] += 1
    total = cells["*"]
    p = mcnemar_exact_p(total["only_baseline"], total["only_candidate"])
    if p >= alpha:
        verdict = "no_significant_difference"
    else:
        verdict = "regression" if total["only_baseline"] > total["only_candidate"] else "improvement"
    return {
        "pairs": sum(total.values()),
        "unpaired": len(a.keys() ^ b.keys()),
        **total,
        "p_value": p,
        "verdict": verdict,
        "per_task": [{"task_key": k, **v} for k, v in sorted(cells.items()) if k != "*"],
    }
