# Development

Active work only; see `docs/platform-plan.md` for the plan.

## M1: platform skeleton

- [ ] Postgres row-level security on every tenant table (`org_id = current_setting('app.org_id')`), with the API
      connecting as a non-owner role and setting `app.org_id` per transaction
- [ ] Enforce roles (owner / admin / member) and add API-key management endpoints (list, create, revoke)
- [ ] Read endpoints still missing: list experiments per project, get / list suite and agent versions
- [ ] Episode fingerprint columns (image digest + the episode log's `fingerprint`: model / code hash, MuJoCo version)
- [ ] Experiment cancellation; worker aborts the runner when its heartbeat reports a lost claim (it currently
      finishes the episode and drops the result)
- [ ] Split into the planned `packages/{env,harness,api,worker,web}` layout (API and worker share one package now)
- [ ] Worker container image + compose service; CI job running `make test` against a Postgres service
- [ ] Fair scheduling across orgs: the claim query is global FIFO, so one org's backlog starves the others
      (seen in the first end-to-end run: the worker ran 4 stale dev-org episodes before ours); per-org round
      robin or weighted claims, plus per-org concurrency quotas
- [ ] Validate suite tasks at creation (known `check`, perturbation keys) instead of failing in the worker,
      where a config error is retried `max_attempts` times
- [ ] Presigned URLs for `trace_uri` / `episode_log_uri` on episode reads, so the web app can open replays
