import uuid

import pytest
from fakes import TASKS
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from robomcp_platform.models import ApiKey, Experiment


def test_org_cannot_read_another_orgs_experiment(make_org):
    a, b = make_org("acme"), make_org("globex")
    exp = a.experiment(TASKS, seeds=[1, 2])

    assert a.get(f"/v1/experiments/{exp['id']}").status_code == 200
    assert b.get(f"/v1/experiments/{exp['id']}").status_code == 404
    assert b.get(f"/v1/experiments/{exp['id']}/episodes").status_code == 404


def test_unknown_and_foreign_ids_are_indistinguishable(make_org):
    a, b = make_org(), make_org()
    exp = a.experiment(TASKS, seeds=[1])
    foreign = b.get(f"/v1/experiments/{exp['id']}")
    missing = b.get(f"/v1/experiments/{uuid.uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_project_list_only_shows_own_projects(make_org):
    a, b = make_org(), make_org()
    a.ok("POST", "/v1/projects", {"name": "alpha"}, 201)
    b.ok("POST", "/v1/projects", {"name": "alpha"}, 201)  # same name in another org is fine
    b.ok("POST", "/v1/projects", {"name": "beta"}, 201)
    assert [p["name"] for p in a.get("/v1/projects").json()] == ["alpha"]
    assert sorted(p["name"] for p in b.get("/v1/projects").json()) == ["alpha", "beta"]


def test_cannot_build_on_another_orgs_project_or_versions(make_org):
    a, b = make_org(), make_org()
    exp = a.experiment(TASKS, seeds=[1])
    b_project = b.ok("POST", "/v1/projects", {"name": "mine"}, 201)
    b_sv = b.ok("POST", f"/v1/projects/{b_project['id']}/suites/s/versions", {"tasks": TASKS})
    b_av = b.ok("POST", f"/v1/projects/{b_project['id']}/agent-versions", {"name": "x", "config": {}})

    # Writing into A's project.
    assert b.post(f"/v1/projects/{exp['project_id']}/suites/s/versions", {"tasks": TASKS}).status_code == 404
    assert b.post(f"/v1/projects/{exp['project_id']}/agent-versions",
                  {"name": "x", "config": {}}).status_code == 404
    # Referencing A's suite version / agent version from B's own project.
    for field in ("suite_version_id", "agent_version_id"):
        body = {"project_id": b_project["id"], "suite_version_id": b_sv["id"], "agent_version_id": b_av["id"],
                "seeds": [1], field: exp[field]}
        assert b.post("/v1/experiments", body).status_code == 404, field


def test_database_rejects_cross_org_references(make_org, sm):
    """Composite (org_id, id) foreign keys: even buggy code cannot attach a row to another org's parent."""
    a, b = make_org(), make_org()
    exp = a.experiment(TASKS, seeds=[1])
    with pytest.raises(IntegrityError), sm.begin() as s:
        s.add(Experiment(org_id=b.org_id, project_id=uuid.UUID(exp["project_id"]),
                         suite_version_id=uuid.UUID(exp["suite_version_id"]),
                         agent_version_id=uuid.UUID(exp["agent_version_id"]), seeds=[1], repeats=1))


def test_requests_without_valid_key_are_rejected(client, make_org):
    org = make_org()
    assert client.get("/v1/projects").status_code == 401
    assert client.get("/v1/projects", headers={"Authorization": "Bearer nope"}).status_code == 401
    forged = org.key[:-4] + "AAAA"
    assert client.get("/v1/projects", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert client.get("/v1/projects", headers=org.headers).status_code == 200


def test_revoked_key_is_rejected(client, make_org, sm):
    org = make_org()
    assert org.get("/v1/me").status_code == 200
    with sm.begin() as s:
        s.execute(update(ApiKey).where(ApiKey.org_id == org.org_id).values(revoked_at=func.now()))
    assert org.get("/v1/me").status_code == 401


def test_key_is_stored_hashed_and_me_reports_owner(make_org, sm):
    org = make_org("initech")
    me = org.ok("GET", "/v1/me")
    assert me["org_slug"] == "initech" and me["role"] == "owner"
    assert org.key.startswith(me["api_key_prefix"])
    with sm() as s:
        stored = s.scalars(select(ApiKey).where(ApiKey.org_id == org.org_id)).one()
    assert org.key not in (stored.key_hash, stored.prefix)
    assert stored.last_used_at is not None
