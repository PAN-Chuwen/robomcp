# RoboMCP

SO-101 robot arm in a MuJoCo tabletop scene, exposed to LLM agents as MCP tools, plus a hand-written agent harness (bare / verify / plan) and an eval that compares harness designs under injected failures.

## Architecture

```
robomcp/
├── pyproject.toml / uv.lock        # uv project; entry points robomcp-server, robomcp-agent
├── typings/mujoco/                 # stubgen-generated stubs for MuJoCo's compiled bindings (pyright);
│                                   #   regenerate command in typings/mujoco/__init__.pyi
├── examples/
│   ├── loop_before_function_calling.py   # agent loop with regex-parsed text actions (offline demo)
│   └── loop_with_function_calling.py     # same loop with structured tool calls
├── docs/                           # platform-plan.md, development.md
├── scripts/probe_*.py              # measured mechanisms: grasp tolerance, camera, gripper signal
├── tests/
│   ├── test_replay.py              # replay reproduces scripted runs, flags the first divergent step
│   ├── test_safety.py              # gate blocks unsafe coordinates before anything moves
│   └── test_sim.py                 # grasp success from proprioception
└── src/robomcp/
    ├── sim.py                      # TabletopSim: scene state, mink IK, pick/place skills, rendering,
    │                               #   live frames, real-time pacing, failure injection (slip)
    ├── server.py                   # MCP server (MCPServer, stdio): 11 async tools
    ├── safety.py                   # deterministic gate on move_to / place_at coordinates
    ├── model/                      # SO-101 MJCF + STL meshes (MuJoCo Menagerie, Apache-2.0) + scene.xml
    └── agent/
        ├── llm.py                  # OpenAI-compatible client (DeepSeek / Gemini), token + cache accounting
        ├── harness.py              # Harness: executor loop, planner and verifier sub-agents, traces
        ├── tasks.py                # eval tasks with scene-based success checks
        ├── replay.py               # re-run a v2 trace on a fresh sim, compare each step, write viewer
        ├── replay.html             # static replay viewer (frames + timeline + per-step check)
        ├── cli.py                  # robomcp-agent run | eval | replay | console
        ├── console.py              # web console server (MJPEG stream, events, POST /run)
        └── console.html            # console page
```

Runtime output goes to `out/` (gitignored): `out/traces/*.jsonl`, `out/eval-*.json`, `out/live/frame.jpg`, `out/replays/<trace>/`.

## Tech stack

Python 3.12 + uv · MuJoCo 3 · mink (IK) · MCP Python SDK v2 (`MCPServer`, `input_schema`) · openai SDK against OpenAI-compatible endpoints · Pillow.

## Quick start

```bash
uv sync
uv run robomcp-server                                   # MCP server over stdio
uv run robomcp-agent run "把红色方块放进托盘" --mode plan --seed 1 --slip 0.5 --slip-mode delayed
uv run robomcp-agent eval --modes bare,verify,plan --seeds 1,2 [--slip 0.5 --slip-mode delayed]
uv run robomcp-agent replay out/traces/<run>.jsonl      # exit 1 if any step diverges from the log
uv run robomcp-agent console                            # http://127.0.0.1:8765
uv run pytest
```

API key: `DEEPSEEK_API_KEY` or `GEMINI_API_KEY` in `.env` (gitignored); on macOS the Gemini key can also come from the Keychain service `gemini-api-key`. `LLM_PROVIDER` / `LLM_MODEL` override the defaults.

## CLI / tool reference

- MCP tools: `get_scene`, `look`, `pick`, `place_in_tray`, `place_at`, `move_to`, `set_gripper`, `go_home`, `reset_scene`, `start_recording`, `save_recording`. Skills return `{ok, message, scene}`.
- Harness hides `look`, `start_recording`, `save_recording`, `reset_scene` from the model (`HIDDEN_TOOLS`).
- Env read by the server: `ROBOMCP_LIVE_DIR` (write live frames + real-time pacing), `ROBOMCP_SLIP` (failure probability), `ROBOMCP_SLIP_MODE` (`immediate` | `delayed`).

## Design principles

- **Geometry in code, decisions in the model.** Skills and derived facts (e.g. `distance_to_tray_m`) are computed deterministically; the model chooses what to do.
- **Success is judged from scene state**, never from the model's claim — both in the verifier and in eval checks.
- **The verifier gets facts, not more reasoning**: it sees the scene before and after execution.
- **Evals must be able to tell harnesses apart**; failure injection exists because the ideal sim made every mode score 10/10.

## Notes for AI assistants

- Traces are v2 (`trace_version` in the start event): every robot call is logged with its full result, harness-internal calls as `harness_call`. Any new robot call in the harness must go through `Harness._call`, or replays stop reproducing.
- MuJoCo rendering must run on the main thread: keep MCP tools `async`. Sync tools run in worker threads and rendering hangs.
- MCP SDK v2 exposes tool schemas as `input_schema` (not `inputSchema`).
- `reset(seed)` seeds the failure-injection RNG; same seed + same actions reproduce the same failures (seed 1 slips on the first placement — used for demos).
- When changing harness prompts or tools, rerun the eval in both the ideal and the delayed-failure setting and report the numbers as they are.
- Commit style: conventional commits (`feat(robomcp): …`, `fix(robomcp): …`, `docs: …`).

## Docs references

- `README.md` — overview, results table, how to run
- `docs/platform-plan.md` — SaaS platform plan, measured mechanisms, milestones
- `docs/development.md` — active todos
