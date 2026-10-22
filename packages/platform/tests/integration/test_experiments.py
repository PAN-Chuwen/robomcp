import threading

import pytest
from fakes import TASKS, FakeRunner
from fastapi.testclient import TestClient

from robomcp_platform.api.app import create_app
from robomcp_platform.stats import wilson_interval
from robomcp_platform.worker import Worker


def test_experiment_expands_tasks_x_seeds_x_repeats(make_org):
    org = make_org()
    exp = org.experiment(TASKS, seeds=[3, 1, 2], repeats=2)

    assert exp["status"] == "queued"
    assert exp["results"]["episodes"] == 2 * 3 * 2
    assert exp["results"]["by_status"]["queued"] == 12
    assert exp["results"]["scored"] == 0 and exp["results"]["success_rate"] is None
    assert exp["results"]["wilson_95"] == [0.0, 1.0]

    page = org.ok("GET", f"/v1/experiments/{exp['id']}/episodes?limit=1000")
    combos = {(e["task_key"], e["seed"], e["repeat_index"]) for e in page["items"]}
    assert page["total"] == 12
    assert combos == {(t["key"], s, r) for t in TASKS for s in (1, 2, 3) for r in (0, 1)}
    assert all(e["status"] == "queued" and e["attempts"] == 0 for e in page["items"])


def test_episode_listing_paginates_and_filters(make_org):
    org = make_org()
    exp = org.experiment(TASKS, seeds=[1, 2, 3])
    first = org.ok("GET", f"/v1/experiments/{exp['id']}/episodes?limit=4&offset=0")
    rest = org.ok("GET", f"/v1/experiments/{exp['id']}/episodes?limit=4&offset=4")
    assert first["total"] == rest["total"] == 6
    assert len(first["items"]) == 4 and len(rest["items"]) == 2
    assert not {e["id"] for e in first["items"]} & {e["id"] for e in rest["items"]}
    assert org.ok("GET", f"/v1/experiments/{exp['id']}/episodes?status=running")["total"] == 0
    assert org.get(f"/v1/experiments/{exp['id']}/episodes?status=bogus").status_code == 422


def test_versions_are_content_addressed(make_org):
    org = make_org()
    proj = org.ok("POST", "/v1/projects", {"name": "p"}, 201)
    base = f"/v1/projects/{proj['id']}"

    v1 = org.post(f"{base}/suites/main/versions", {"tasks": TASKS})
    again = org.post(f"{base}/suites/main/versions", {"tasks": [dict(reversed(t.items())) for t in TASKS]})
    v2 = org.post(f"{base}/suites/main/versions", {"tasks": TASKS[:1]})
    assert (v1.status_code, again.status_code, v2.status_code) == (201, 200, 201)
    assert again.json()["id"] == v1.json()["id"]
    assert (v1.json()["version"], v2.json()["version"]) == (1, 2)

    a1 = org.post(f"{base}/agent-versions", {"name": "planner", "config": {"mode": "plan", "model": "m"}})
    a1_again = org.post(f"{base}/agent-versions", {"name": "planner", "config": {"model": "m", "mode": "plan"}})
    a2 = org.post(f"{base}/agent-versions", {"name": "planner", "config": {"mode": "verify", "model": "m"}})
    other = org.post(f"{base}/agent-versions", {"name": "bare", "config": {"mode": "plan", "model": "m"}})
    assert (a1.status_code, a1_again.status_code, a2.status_code, other.status_code) == (201, 200, 201, 201)
    assert a1_again.json()["id"] == a1.json()["id"]
    assert (a2.json()["version"], other.json()["version"]) == (2, 1)
    assert a1.json()["content_hash"] == other.json()["content_hash"]


@pytest.mark.parametrize("tasks", [[], [{"key": "a"}, {"key": "a"}], [{"key": "has space"}], [{"goal": "no key"}]])
def test_rejects_invalid_suites(make_org, tasks):
    org = make_org()
    proj = org.ok("POST", "/v1/projects", {"name": "p"}, 201)
    assert org.post(f"/v1/projects/{proj['id']}/suites/s/versions", {"tasks": tasks}).status_code == 422


def test_rejects_invalid_experiments(make_org, settings, engine):
    org = make_org()
    exp = org.experiment(TASKS, seeds=[1])
    body = {k: exp[k] for k in ("project_id", "suite_version_id", "agent_version_id")}
    assert org.post("/v1/experiments", {**body, "seeds": []}).status_code == 422
    assert org.post("/v1/experiments", {**body, "seeds": [1, 1]}).status_code == 422
    assert org.post("/v1/experiments", {**body, "seeds": [1], "repeats": 0}).status_code == 422

    other_project = org.ok("POST", "/v1/projects", {"name": "other"}, 201)
    assert org.post("/v1/experiments", {**body, "project_id": other_project["id"], "seeds": [1]}).status_code == 422

    capped = settings.model_copy(update={"max_episodes_per_experiment": 5})
    with TestClient(create_app(capped, engine)) as c:
        r = c.post("/v1/experiments", json={**body, "seeds": [1, 2, 3]}, headers=org.headers)  # 2 x 3 = 6
    assert r.status_code == 422 and "limit" in r.json()["detail"]


def test_worker_runs_experiment_to_completion_with_wilson_summary(make_org, sm, settings):
    org = make_org()
    exp = org.experiment(TASKS, seeds=[0, 1, 2, 3, 4], repeats=2, agent_config={"mode": "verify"})
    runner = FakeRunner(decide=lambda spec: spec.seed % 2 == 0 or spec.task_key == "red")

    done = Worker(sm, runner, settings, worker_id="w1").run_forever(threading.Event(), max_episodes=20)
    assert done == 20
    assert Worker(sm, runner, settings).run_once() is False  # queue is drained

    result = org.ok("GET", f"/v1/experiments/{exp['id']}")
    expected = sum(1 for t in TASKS for s in range(5) for _ in range(2) if s % 2 == 0 or t["key"] == "red")
    r = result["results"]
    assert result["status"] == "completed" and result["finished_at"] is not None
    assert (r["successes"], r["scored"]) == (expected, 20)
    assert r["wilson_95"] == pytest.approx(list(wilson_interval(expected, 20)))
    per_task = {t["task_key"]: t for t in r["per_task"]}
    assert (per_task["red"]["successes"], per_task["all"]["successes"]) == (10, 6)

    spec = runner.calls[0]
    assert spec.agent_config == {"mode": "verify"} and spec.task["key"] == spec.task_key and spec.attempt == 1
    episodes = org.ok("GET", f"/v1/experiments/{exp['id']}/episodes?limit=100")["items"]
    assert all(e["claimed_by"] == "w1" and e["trace_uri"] and e["metrics"]["steps"] == 3 for e in episodes)
    assert all(e["status"] == ("succeeded" if e["success"] else "failed") for e in episodes)


@pytest.mark.parametrize("task", [
    {"key": "fold_towel"},  # no built-in check with that name
    {"key": "red", "check": "nope"},
    {"key": "red", "perturbations": {"slip": 1.5}},
    {"key": "red", "perturbations": {"slip_mode": "sometimes"}},
    {"key": "red", "perturbations": {"gravity": 0}},
])
def test_rejects_suite_tasks_the_runner_cannot_run(make_org, task):
    org = make_org()
    proj = org.ok("POST", "/v1/projects", {"name": "p"}, 201)
    assert org.post(f"/v1/projects/{proj['id']}/suites/main/versions", {"tasks": [task]}).status_code == 422


def test_accepts_a_task_with_a_renamed_check_and_perturbations(make_org):
    org = make_org()
    proj = org.ok("POST", "/v1/projects", {"name": "p"}, 201)
    task = {"key": "red_slippery", "check": "red", "perturbations": {"slip": 0.5, "slip_mode": "delayed"}}
    v = org.ok("POST", f"/v1/projects/{proj['id']}/suites/main/versions", {"tasks": [task]}, 201)
    assert v["tasks"] == [task]


@pytest.mark.parametrize("config", [{"mode": "yolo"}, {"max_turns": 0}, {"max_verify": "2"}])
def test_rejects_agent_configs_the_harness_cannot_run(make_org, config):
    org = make_org()
    proj = org.ok("POST", "/v1/projects", {"name": "p"}, 201)
    assert org.post(f"/v1/projects/{proj['id']}/agent-versions", {"name": "a", "config": config}).status_code == 422
