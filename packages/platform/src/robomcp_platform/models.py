"""SQLAlchemy models. Every tenant table carries `org_id`.

Child tables reference their parent through a composite foreign key `(org_id, parent_id)` onto a
`UNIQUE (org_id, id)` of the parent, so a row can never point at another organisation's row even if
application code forgets a check. Suite and agent versions are immutable (enforced by a trigger in the
initial migration).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROLES = ("owner", "admin", "member")
EXPERIMENT_STATUSES = ("queued", "running", "completed")
# succeeded / failed: the episode ran to the end and the task check passed / did not pass.
# error: no result could be produced (runner raised or the worker died) after max attempts.
EPISODE_STATUSES = ("queued", "running", "succeeded", "failed", "error")
TERMINAL_EPISODE_STATUSES = ("succeeded", "failed", "error")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB, datetime: DateTime(timezone=True)}


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def _org_id() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    """Global identity (GitHub OAuth attaches here in M2); org access goes through memberships."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id"),
        CheckConstraint(_in("role", ROLES), name="role"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = _created_at()


class ApiKey(Base):
    """Only a SHA-256 of the key is stored; `prefix` is a non-secret display handle."""

    __tablename__ = "api_keys"
    __table_args__ = (
        # The key's user must be a member of the key's org.
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["memberships.org_id", "memberships.user_id"], ondelete="CASCADE"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    user_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created_at()
    last_used_at: Mapped[datetime | None] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "name"), UniqueConstraint("org_id", "id"))

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class Suite(Base):
    __tablename__ = "suites"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    project_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class SuiteVersion(Base):
    """Immutable snapshot of a suite's tasks (a JSON list of objects, each with a unique `key`)."""

    __tablename__ = "suite_versions"
    __table_args__ = (
        UniqueConstraint("suite_id", "version"),
        UniqueConstraint("suite_id", "content_hash"),
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(["org_id", "suite_id"], ["suites.org_id", "suites.id"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    suite_id: Mapped[uuid.UUID] = mapped_column()
    version: Mapped[int] = mapped_column(Integer)
    tasks: Mapped[list[Any]] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()


class AgentVersion(Base):
    """Immutable agent configuration (model, prompts, harness mode, ...) with its content hash."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "name", "version"),
        UniqueConstraint("project_id", "name", "content_hash"),
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    project_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        CheckConstraint(_in("status", EXPERIMENT_STATUSES), name="status"),
        CheckConstraint("repeats >= 1", name="repeats_positive"),
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["org_id", "suite_version_id"], ["suite_versions.org_id", "suite_versions.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["org_id", "agent_version_id"], ["agent_versions.org_id", "agent_versions.id"], ondelete="RESTRICT"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    project_id: Mapped[uuid.UUID] = mapped_column(index=True)
    suite_version_id: Mapped[uuid.UUID] = mapped_column()
    agent_version_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str | None] = mapped_column(String(200))
    seeds: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    repeats: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'queued'"))
    created_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column()


class Episode(Base):
    """One (task, seed, repeat) run of an experiment; also the job-queue row."""

    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("experiment_id", "task_key", "seed", "repeat_index"),
        CheckConstraint(_in("status", EPISODE_STATUSES), name="status"),
        ForeignKeyConstraint(
            ["org_id", "experiment_id"], ["experiments.org_id", "experiments.id"], ondelete="CASCADE"
        ),
        # Claim order for queued rows, and the reaper's scan of running rows.
        Index("ix_episodes_queued", "created_at", "id", postgresql_where=text("status = 'queued'")),
        Index("ix_episodes_running_heartbeat", "heartbeat_at", postgresql_where=text("status = 'running'")),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org_id()
    experiment_id: Mapped[uuid.UUID] = mapped_column()
    task_key: Mapped[str] = mapped_column(String(200))
    seed: Mapped[int] = mapped_column(BigInteger)
    repeat_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'queued'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    heartbeat_at: Mapped[datetime | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    success: Mapped[bool | None] = mapped_column()
    metrics: Mapped[dict[str, Any] | None] = mapped_column()
    trace_uri: Mapped[str | None] = mapped_column(Text)
    episode_log_uri: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
