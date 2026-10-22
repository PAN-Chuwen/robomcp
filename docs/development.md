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
- [ ] Presigned URLs for `trace_uri` / `episode_log_uri` on episode reads, so the web app can open replays

## M2: web app

- [ ] GitHub OAuth sign-in with organisations and roles, replacing API-key sign-in; then the cookie should carry a
      server-side session id (or a sealed token) instead of the raw API key it holds now
- [ ] Session cookie `secure` follows the request protocol; behind a TLS-terminating proxy, trust `X-Forwarded-Proto`
      or force `secure` in production
- [ ] Comparison: list the discordant pairs with both episode ids (needs an API endpoint), so each piece of evidence
      links to its two replays
- [ ] Replay: carry the agent's last observation forward as its belief and diff that against later truth; per-step
      diffs cannot show the delayed slip, because the episode log records truth at the same instant as the
      (still correct) observation and the cube only slips afterwards
- [ ] Replay: frames / video once workers store them; link the eval check's before/after scenes side by side
- [ ] Experiment list: server-side pagination (the page asks for the API's maximum of 200); episode filters by task
      and seed (needs API query parameters)
- [ ] Start experiments from the UI (suite version × agent version × seeds × repeats)
- [ ] CI job for packages/web: `npm ci && npm test && npm run lint && npm run typecheck && npm run build`, plus a
      route-handler test for sign-in against a stubbed API
