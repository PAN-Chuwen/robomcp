# Development

Active work only; see `docs/platform-plan.md` for the plan.

## M1: platform skeleton

- [ ] Implement `HarnessRunner` in `packages/platform/src/robomcp_platform/runner.py` (reset with seed, run the
      harness from `agent_config`, score from scene state, return metrics + trace / episode-log URIs)
- [ ] Object storage: S3 client for MinIO (bucket bootstrap, upload traces / frames from the worker, presigned
      URLs on episode reads); the `ROBOMCP_S3_*` settings exist but nothing uses them yet
- [ ] Postgres row-level security on every tenant table (`org_id = current_setting('app.org_id')`), with the API
      connecting as a non-owner role and setting `app.org_id` per transaction
- [ ] Enforce roles (owner / admin / member) and add API-key management endpoints (list, create, revoke)
- [ ] Read endpoints still missing: list experiments per project, get / list suite and agent versions
- [ ] Episode fingerprint columns (image digest + the episode log's `fingerprint`: model / code hash, MuJoCo version)
- [ ] Experiment cancellation; worker aborts the runner when its heartbeat reports a lost claim (it currently
      finishes the episode and drops the result)
- [ ] Split into the planned `packages/{env,harness,api,worker,web}` layout (API and worker share one package now)
- [ ] Worker container image + compose service; CI job running `make test` against a Postgres service
