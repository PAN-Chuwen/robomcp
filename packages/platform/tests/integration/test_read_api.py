"""Read endpoints for the web app: listings, paired comparison, pass^k, artifacts."""

from __future__ import annotations

from pathlib import Path

from fakes import TASKS, FakeRunner
from fastapi.testclient import TestClient

from robomcp_platform.api.app import create_app
from robomcp_platform.runner import EpisodeResult, EpisodeSpec
from robomcp_platform.storage import LocalStore
from robomcp_platform.worker import Worker


def _drain(sm, settings, runner) -> None:
    worker = Worker(sm, runner, settings, "w-read")
    while worker.run_once():
        pass


def test_project_listings_are_org_scoped(make_org):
    org, other = make_org(), make_org()
    exp = org.experiment(TASKS, seeds=[1])
    project_id = exp["project_id"]
    assert org.ok("GET", f"/v1/projects/{project_id}")["name"] == "p"
    assert [e["id"] for e in org.ok("GET", f"/v1/projects/{project_id}/experiments")] == [exp["id"]]
    assert len(org.ok("GET", f"/v1/projects/{project_id}/suite-versions")) == 1
    assert [a["name"] for a in org.ok("GET", f"/v1/projects/{project_id}/agent-versions")] == ["agent"]
    for path in ("", "/experiments", "/suite-versions", "/agent-versions"):
        assert other.get(f"/v1/projects/{project_id}{path}").status_code == 404


def test_paired_comparison_flags_a_regression(make_org, sm, settings):
    org = make_org()
    seeds = list(range(1, 7))
    base = org.experiment([TASKS[0]], seeds=seeds, agent_config={"mode": "plan"})
    _drain(sm, settings, FakeRunner(decide=lambda s: True))
    cand = org.experiment([TASKS[0]], seeds=seeds, agent_config={"mode": "bare"})
    _drain(sm, settings, FakeRunner(decide=lambda s: False))

    cmp = org.ok("GET", f"/v1/experiments/compare?baseline={base['id']}&candidate={cand['id']}")
    assert (cmp["pairs"], cmp["only_baseline"], cmp["only_candidate"]) == (6, 6, 0)
    assert abs(cmp["p_value"] - 2 / 64) < 1e-12
    assert cmp["verdict"] == "regression" and cmp["same_suite_version"] is True
    assert cmp["per_task"] == [{"task_key": TASKS[0]["key"], "both": 0, "only_baseline": 6,
                                "only_candidate": 0, "neither": 0}]


def test_small_paired_difference_is_not_significant(make_org, sm, settings):
    org = make_org()
    base = org.experiment([TASKS[0]], seeds=[1, 2, 3])
    _drain(sm, settings, FakeRunner(decide=lambda s: True))
    cand = org.experiment([TASKS[0]], seeds=[1, 2, 3], agent_config={"mode": "bare"})
    _drain(sm, settings, FakeRunner(decide=lambda s: s.seed != 1))
    cmp = org.ok("GET", f"/v1/experiments/compare?baseline={base['id']}&candidate={cand['id']}")
    assert cmp["only_baseline"] == 1 and cmp["verdict"] == "no_significant_difference"


def test_compare_rejects_experiments_from_different_projects(make_org):
    org = make_org()
    a = org.experiment(TASKS, seeds=[1], project="one")
    b = org.experiment(TASKS, seeds=[1], project="two")
    assert org.get(f"/v1/experiments/compare?baseline={a['id']}&candidate={b['id']}").status_code == 422


def test_pass_k_from_repeats(make_org, sm, settings):
    org = make_org()
    exp = org.experiment([TASKS[0]], seeds=[1], repeats=4)
    _drain(sm, settings, FakeRunner(decide=lambda s: s.repeat_index != 0))  # 3 of 4 repeats succeed
    pass_k = org.ok("GET", f"/v1/experiments/{exp['id']}")["results"]["pass_k"]
    assert [round(p["value"], 6) for p in pass_k] == [0.75, 0.5, 0.25, 0.0]


class _ArtifactRunner:
    def __init__(self, store: LocalStore, tmp: Path):
        self.store, self.tmp = store, tmp

    def run(self, spec: EpisodeSpec) -> EpisodeResult:
        src = self.tmp / "trace.jsonl"
        src.write_text('{"kind": "start"}\n')
        uri = self.store.put(f"{spec.org_id}/{spec.episode_id}/trace.jsonl", src)
        return EpisodeResult(success=True, trace_uri=uri)


def test_artifacts_are_served_to_the_owning_org_only(make_org, sm, settings, engine, tmp_path):
    store = LocalStore(tmp_path / "artifacts")
    with TestClient(create_app(settings, engine, store=store)) as client:
        org, other = make_org(), make_org()
        org.client = other.client = client
        exp = org.experiment([TASKS[0]], seeds=[1])
        _drain(sm, settings, _ArtifactRunner(store, tmp_path))
        ep = org.ok("GET", f"/v1/experiments/{exp['id']}/episodes")["items"][0]
        assert org.ok("GET", f"/v1/episodes/{ep['id']}")["status"] == "succeeded"
        r = org.get(f"/v1/episodes/{ep['id']}/artifacts/trace")
        assert r.status_code == 200 and r.text == '{"kind": "start"}\n'
        assert org.get(f"/v1/episodes/{ep['id']}/artifacts/episode_log").status_code == 404  # none stored
        assert org.get(f"/v1/episodes/{ep['id']}/artifacts/frames").status_code == 422
        assert other.get(f"/v1/episodes/{ep['id']}/artifacts/trace").status_code == 404


def test_local_store_refuses_paths_outside_its_root(tmp_path):
    import pytest

    store = LocalStore(tmp_path / "artifacts")
    with pytest.raises(ValueError):
        store.get((tmp_path / "secret.txt").as_uri())
