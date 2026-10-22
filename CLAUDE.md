# RoboMCP

SO-101 robot arm in a MuJoCo tabletop scene, exposed to LLM agents as MCP tools, plus a hand-written agent harness (bare / verify / plan) and an eval that compares harness designs under injected failures.

## Architecture

```
robomcp/
├── pyproject.toml / uv.lock        # uv workspace root (members: packages/*); entry points robomcp-server, robomcp-agent
├── docker-compose.yml              # dev services: Postgres 16 (host :5442), MinIO (host :9010, console :9011)
├── .env.example                    # copy to .env: compose credentials, ROBOMCP_DATABASE_URL, queue timings
├── Makefile                        # make dev | services | migrate | api | worker | test | test-unit | down
├── typings/mujoco/                 # stubgen-generated stubs for MuJoCo's compiled bindings (pyright);
│                                   #   regenerate command in typings/mujoco/__init__.pyi
├── examples/
│   ├── loop_before_function_calling.py   # agent loop with regex-parsed text actions (offline demo)
│   └── loop_with_function_calling.py     # same loop with structured tool calls
├── docs/                           # platform-plan.md, development.md, engineering-notes.md
├── scripts/probe_*.py              # measured mechanisms: grasp tolerance, camera, gripper signal
├── tests/
│   ├── test_replay.py              # replay reproduces scripted runs, flags the first divergent step
│   ├── test_safety.py              # gate blocks unsafe coordinates before anything moves
│   └── test_sim.py                 # grasp success from proprioception
└── src/robomcp/
    ├── sim.py                      # TabletopSim: scene state, mink IK, pick/place skills, rendering,
    │                               #   live frames, real-time pacing, failure injection (slip)
    ├── perception.py               # Perception seam: where object position estimates come from (oracle now)
    ├── server.py                   # MCP server (MCPServer, stdio): 11 async tools; writes the episode log
    ├── safety.py                   # deterministic gate on move_to / place_at coordinates
    ├── model/                      # SO-101 MJCF + STL meshes (MuJoCo Menagerie, Apache-2.0) + scene.xml
    └── agent/
        ├── llm.py                  # OpenAI-compatible client (DeepSeek / Gemini), token + cache accounting
        ├── harness.py              # Harness: executor loop, planner and verifier sub-agents, traces
        ├── tasks.py                # eval tasks with scene-based success checks
        ├── replay.py               # re-run an episode log on a fresh sim, compare each step, write viewer
        ├── replay.html             # static replay viewer (frames + timeline + per-step check)
        ├── cli.py                  # robomcp-agent run | eval | replay | console
        ├── console.py              # web console server (MJPEG stream, events, POST /run)
        └── console.html            # console page
packages/
└── platform/                       # robomcp-platform: SaaS backend (M1 skeleton)
    ├── pyproject.toml              # entry points robomcp-platform (admin CLI), robomcp-worker
    ├── alembic.ini                 # migrations; file names YYYYMMDD_HHMMSS_slug
    ├── src/robomcp_platform/
    │   ├── config.py               # Settings (pydantic-settings, ROBOMCP_* env / .env)
    │   ├── db.py                   # engine + sessionmaker factories
    │   ├── models.py               # tenant tables; composite (org_id, id) FKs; status enums as CHECKs
    │   ├── migrations/             # Alembic env + versions/ (initial schema + immutability trigger)
    │   ├── security.py             # API keys: rmcp_ + 256-bit secret, stored as SHA-256 + display prefix
    │   ├── hashing.py              # canonical-JSON content hashes for suite / agent versions
    │   ├── stats.py                # Wilson score interval
    │   ├── tenancy.py              # create org + owner + key, issue keys
    │   ├── queue.py                # Postgres job queue: expand, claim (SKIP LOCKED), heartbeat, complete,
    │   │                           #   fail, reap stale heartbeats
    │   ├── results.py              # experiment aggregates (overall + per task)
    │   ├── runner.py               # EpisodeSpec / EpisodeResult / EpisodeRunner; HarnessRunner runs the robomcp
    │   │                           #   harness, scores from episode-log truth, uploads trace + episode log
    │   ├── storage.py              # artifact store: S3/MinIO (path-style) or local directory
    │   ├── worker.py               # robomcp-worker loop (runner on main thread, heartbeat thread)
    │   ├── cli.py                  # robomcp-platform bootstrap | create-api-key
    │   └── api/                    # FastAPI: app.py (factory), deps.py (session, bearer auth),
    │                               #   schemas.py, routes.py (/v1)
    └── tests/
        ├── unit/                   # Wilson interval, key hashing (no DB)
        └── integration/            # throwaway DB per session; tenancy, queue, experiments, migrations;
                                    #   fakes.py: FakeRunner, ScriptedLLM (drives the real harness offline)
```

Runtime output goes to `out/` (gitignored): `out/traces/*.jsonl`, `out/eval-*.json`, `out/traces/*.env.jsonl`, `out/live/frame.jpg`, `out/replays/<trace>/`.

## Tech stack

Python 3.12 + uv · MuJoCo 3 · mink (IK) · MCP Python SDK v2 (`MCPServer`, `input_schema`) · openai SDK against OpenAI-compatible endpoints · Pillow.
Platform: FastAPI · SQLAlchemy 2 + psycopg 3 · Alembic · pydantic-settings · Postgres 16 · MinIO (S3).

## Quick start

```bash
uv sync
uv run robomcp-server                                   # MCP server over stdio
uv run robomcp-agent run "把红色方块放进托盘" --mode plan --seed 1 --slip 0.5 --slip-mode delayed
uv run robomcp-agent eval --modes bare,verify,plan --seeds 1,2 [--slip 0.5 --slip-mode delayed]
uv run robomcp-agent replay out/traces/<run>.jsonl      # exit 1 if any step diverges from the log
uv run robomcp-agent console                            # http://127.0.0.1:8765
uv run pytest

# platform backend (packages/platform); needs Docker
cp .env.example .env
make dev                                                # compose up --wait, alembic upgrade head, API on :8000
uv run --package robomcp-platform robomcp-platform bootstrap --org-name Acme --org-slug acme --email you@example.com
make worker                                             # robomcp-worker: runs queued episodes with the harness (needs an LLM key)
make test                                               # unit + integration (creates/drops robomcp_test_<random>)
```

API key: `DEEPSEEK_API_KEY` or `GEMINI_API_KEY` in `.env` (gitignored); on macOS the Gemini key can also come from the Keychain service `gemini-api-key`. `LLM_PROVIDER` / `LLM_MODEL` override the defaults.

## CLI / tool reference

- MCP tools: `get_scene`, `look`, `pick`, `place_in_tray`, `place_at`, `move_to`, `set_gripper`, `go_home`, `reset_scene`, `start_recording`, `save_recording`. Skills return `{ok, message, scene}`.
- Harness hides `look`, `start_recording`, `save_recording`, `reset_scene` from the model (`HIDDEN_TOOLS`).
- Env read by the server: `ROBOMCP_LIVE_DIR` (write live frames + real-time pacing), `ROBOMCP_SLIP` (failure probability), `ROBOMCP_SLIP_MODE` (`immediate` | `delayed`).
- Platform API (`Authorization: Bearer rmcp_…`, OpenAPI at `/docs`): `GET /healthz`, `GET /v1/me`,
  `POST|GET /v1/projects`, `POST /v1/projects/{id}/suites/{name}/versions` (201 new / 200 identical tasks),
  `POST /v1/projects/{id}/agent-versions` (201 / 200), `POST /v1/experiments` (expands tasks × seeds × repeats),
  `GET /v1/experiments/{id}` (status + successes / scored + Wilson 95%, per task),
  `GET /v1/experiments/{id}/episodes?status=&limit=&offset=`.
- Platform env: `ROBOMCP_DATABASE_URL`, `ROBOMCP_TEST_DATABASE_URL` (test server), `ROBOMCP_HEARTBEAT_INTERVAL_S`,
  `ROBOMCP_HEARTBEAT_TIMEOUT_S`, `ROBOMCP_MAX_ATTEMPTS`, `ROBOMCP_WORKER_RUNNER` (`module:factory`).

## Design principles

- **Geometry in code, decisions in the model.** Skills and derived facts (e.g. `distance_to_tray_m`) are computed deterministically; the model chooses what to do.
- **Success is judged from scene state**, never from the model's claim — both in the verifier and in eval checks.
- **The verifier gets facts, not more reasoning**: it sees the scene before and after execution.
- **Evals must be able to tell harnesses apart**; failure injection exists because the ideal sim made every mode score 10/10.

## Notes for AI assistants

- A run is a trace v3 (`<run>.jsonl`, agent side; each robot call carries its `step`) plus the environment's episode log (`<run>.env.jsonl`, observation + ground truth per call, written by the server when `ROBOMCP_EPISODE_LOG` is set). Every robot call in the harness must go through `Harness._call`, or step numbers stop matching.
- Tools return observations (`sim.observe()`); ground truth (`sim.truth()`) is only for scoring, replay and failure injection. Skills aim at `perceived_state`, never `object_state`.
- MuJoCo rendering must run on the main thread: keep MCP tools `async`. Sync tools run in worker threads and rendering hangs.
- MCP SDK v2 exposes tool schemas as `input_schema` (not `inputSchema`).
- `reset(seed)` seeds the failure-injection RNG; same seed + same actions reproduce the same failures (seed 1 slips on the first placement — used for demos).
- When changing harness prompts or tools, rerun the eval in both the ideal and the delayed-failure setting and report the numbers as they are.
- Commit style: conventional commits (`feat(robomcp): …`, `fix(robomcp): …`, `docs: …`; `feat(platform): …` for packages/platform).
- Platform: every tenant query filters by the principal's `org_id`; foreign rows are 404, never 403. Child tables
  reference parents via composite `(org_id, parent_id)` FKs, so cross-org links fail in the database too.
- Platform: queue functions never commit; run each in its own `sm.begin()` transaction. Lock episode rows before
  the experiment row. Worker writes are guarded by `claimed_by = me AND status = 'running'`.
- Platform: episode status `succeeded`/`failed` = task check passed / not; `error` = no result after
  `max_attempts`. `error` is excluded from the scored n.
- Platform: schema changes go through `make migrate`-able Alembic revisions (`alembic -c packages/platform/alembic.ini
  revision --autogenerate -m …`); suite_versions / agent_versions are immutable (DB trigger).

## Docs references

- `README.md` — overview, results table, how to run
- `docs/platform-plan.md` — SaaS platform plan, measured mechanisms, milestones
- `docs/development.md` — active todos
- `docs/engineering-notes.md` — motivation / difficulty / resolution per decision, architecture (interview prep); add an entry for every notable change
