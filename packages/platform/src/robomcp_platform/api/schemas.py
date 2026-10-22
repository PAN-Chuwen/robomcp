"""Request and response bodies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME = Field(min_length=1, max_length=200)


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MeOut(BaseModel):
    org_id: uuid.UUID
    org_name: str
    org_slug: str
    user_id: uuid.UUID
    email: str
    role: str
    api_key_prefix: str


class ProjectCreate(BaseModel):
    name: str = NAME


class ProjectOut(Orm):
    id: uuid.UUID
    name: str
    created_at: datetime


class TaskSpec(BaseModel):
    """A task in a suite. `key` identifies it within the suite; other fields pass through to the runner."""

    model_config = ConfigDict(extra="allow")
    key: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.\-]+$")
    goal: str | None = None


class SuiteVersionCreate(BaseModel):
    tasks: list[TaskSpec] = Field(min_length=1)

    @field_validator("tasks")
    @classmethod
    def _unique_keys(cls, tasks: list[TaskSpec]) -> list[TaskSpec]:
        keys = [t.key for t in tasks]
        if len(set(keys)) != len(keys):
            raise ValueError("task keys must be unique within a suite version")
        return tasks


class SuiteVersionOut(Orm):
    id: uuid.UUID
    suite_id: uuid.UUID
    suite_name: str
    version: int
    content_hash: str
    tasks: list[dict[str, Any]]
    created_at: datetime


class AgentVersionCreate(BaseModel):
    name: str = NAME
    config: dict[str, Any]


class AgentVersionOut(Orm):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    content_hash: str
    config: dict[str, Any]
    created_at: datetime


class ExperimentCreate(BaseModel):
    project_id: uuid.UUID
    suite_version_id: uuid.UUID
    agent_version_id: uuid.UUID
    seeds: list[int] = Field(min_length=1, max_length=10_000)
    repeats: int = Field(default=1, ge=1, le=1000)
    name: str | None = Field(default=None, max_length=200)

    @field_validator("seeds")
    @classmethod
    def _unique_seeds(cls, seeds: list[int]) -> list[int]:
        if len(set(seeds)) != len(seeds):
            raise ValueError("seeds must be unique")
        if any(not -(2**63) <= s < 2**63 for s in seeds):
            raise ValueError("seeds must fit in a signed 64-bit integer")
        return seeds


class Tally(BaseModel):
    episodes: int
    by_status: dict[str, int]
    successes: int
    scored: int = Field(description="succeeded + failed; error episodes are excluded")
    success_rate: float | None
    wilson_95: tuple[float, float]


class TaskTally(Tally):
    task_key: str


class Results(Tally):
    per_task: list[TaskTally]


class ExperimentOut(Orm):
    id: uuid.UUID
    project_id: uuid.UUID
    suite_version_id: uuid.UUID
    agent_version_id: uuid.UUID
    name: str | None
    seeds: list[int]
    repeats: int
    status: str
    created_at: datetime
    finished_at: datetime | None
    results: Results


class EpisodeOut(Orm):
    id: uuid.UUID
    experiment_id: uuid.UUID
    task_key: str
    seed: int
    repeat_index: int
    status: str
    attempts: int
    claimed_by: str | None
    heartbeat_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    success: bool | None
    metrics: dict[str, Any] | None
    trace_uri: str | None
    episode_log_uri: str | None
    error: str | None


class EpisodePage(BaseModel):
    items: list[EpisodeOut]
    total: int
    limit: int
    offset: int
