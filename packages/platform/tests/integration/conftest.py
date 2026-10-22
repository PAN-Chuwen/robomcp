"""Integration fixtures: a throwaway Postgres database per test session.

The server comes from ROBOMCP_TEST_DATABASE_URL, else ROBOMCP_DATABASE_URL (env or .env); only its
host/credentials are used. A database `robomcp_test_<random>` is created and migrated with Alembic at
session start and dropped at session end. Tables are truncated after every test.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from robomcp_platform.api.app import create_app
from robomcp_platform.config import Settings
from robomcp_platform.db import make_engine, make_sessionmaker
from robomcp_platform.models import Base
from robomcp_platform.tenancy import create_org_with_owner

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def pytest_collection_modifyitems(items):
    here = Path(__file__).parent
    for item in items:
        if here in Path(item.fspath).parents:
            item.add_marker(pytest.mark.integration)


def _server_url() -> str:
    return os.environ.get("ROBOMCP_TEST_DATABASE_URL") or Settings().database_url


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logging"] = False
    return cfg


@contextmanager
def throwaway_database(migrate: bool = True) -> Iterator[str]:
    """Create a uniquely named database (optionally migrated to head), yield its URL, then drop it."""
    server = make_url(_server_url())
    name = f"robomcp_test_{uuid.uuid4().hex[:12]}"
    admin = make_engine(server.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:
        admin.dispose()
        pytest.exit(f"integration tests need Postgres at {server.render_as_string()} "
                    f"(run `make services`): {exc}", returncode=3)
    url = server.set(database=name).render_as_string(hide_password=False)
    try:
        if migrate:
            command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    with throwaway_database() as url:
        yield url


@pytest.fixture(scope="session")
def engine(db_url: str) -> Iterator[Engine]:
    eng = make_engine(db_url, pool_size=20, max_overflow=10)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def sm(engine: Engine) -> sessionmaker[Session]:
    return make_sessionmaker(engine)


@pytest.fixture(autouse=True)
def _truncate(request) -> Iterator[None]:
    yield
    if "engine" in request.fixturenames:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        with request.getfixturevalue("engine").begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def settings(db_url: str) -> Settings:
    return Settings(database_url=db_url, heartbeat_interval_s=0.1, heartbeat_timeout_s=0.5, max_attempts=3,
                    poll_interval_s=0.01)


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(settings, engine)) as c:
        yield c


class OrgHandle:
    def __init__(self, client: TestClient, org_id: uuid.UUID, key: str):
        self.client, self.org_id, self.key = client, org_id, key
        self.headers = {"Authorization": f"Bearer {key}"}

    def get(self, path: str, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path: str, json=None, **kw):
        return self.client.post(path, json=json, headers=self.headers, **kw)

    def ok(self, method: str, path: str, json=None, expect: int | tuple[int, ...] = (200, 201)) -> dict:
        r = self.post(path, json) if method == "POST" else self.get(path)
        expected = expect if isinstance(expect, tuple) else (expect,)
        assert r.status_code in expected, (r.status_code, r.text)
        return r.json()

    def experiment(self, tasks: list[dict], seeds: list[int], repeats: int = 1, project: str = "p",
                   agent_config: dict | None = None) -> dict:
        """Create project + suite version + agent version + experiment through the API."""
        projects = {p["name"]: p for p in self.ok("GET", "/v1/projects")}
        proj = projects.get(project) or self.ok("POST", "/v1/projects", {"name": project}, 201)
        sv = self.ok("POST", f"/v1/projects/{proj['id']}/suites/main/versions", {"tasks": tasks})
        av = self.ok("POST", f"/v1/projects/{proj['id']}/agent-versions",
                     {"name": "agent", "config": agent_config or {"mode": "plan"}})
        return self.ok("POST", "/v1/experiments", {
            "project_id": proj["id"], "suite_version_id": sv["id"], "agent_version_id": av["id"],
            "seeds": seeds, "repeats": repeats,
        }, 201)


@pytest.fixture
def make_org(client: TestClient, sm: sessionmaker[Session]):
    def _make(slug: str | None = None) -> OrgHandle:
        slug = slug or f"org-{uuid.uuid4().hex[:8]}"
        with sm.begin() as s:
            made = create_org_with_owner(s, org_name=slug, org_slug=slug, email=f"owner@{slug}.test")
            org_id, key = made.org.id, made.api_key.plaintext
        return OrgHandle(client, org_id, key)

    return _make
