# RoboMCP

An SO-101 robot arm in a MuJoCo tabletop scene, exposed to LLM agents as MCP tools, plus a hand-written agent harness and an eval that compares harness designs.

让大模型 Agent 通过 MCP 操作 3D 物理场景里的机械臂，并用一套自动评测比较不同的 Harness 设计。

```
LLM agent (Claude Code, or the harness in this repo)
        │  MCP (stdio, JSON-RPC)
        ▼
server.py   11 tools: get_scene, look, pick, place_in_tray, place_at,
            move_to, set_gripper, go_home, reset_scene, start/save_recording
        ▼
sim.py      skills (pick / place) → inverse kinematics (mink) → MuJoCo physics
            SO-101 arm, three cubes, one tray
```

## What is in here

- **MCP server** (`src/robomcp/server.py`): high-level skills (pick an object, place it in the tray) instead of raw joint angles. Every skill returns `ok`, a reason, and the full scene state, so the agent can check its own work. Tools are `async` because MuJoCo's OpenGL renderer must run on the main thread.
- **Simulation** (`src/robomcp/sim.py`): top-down grasp IK with [mink](https://github.com/kevinzakka/mink); the 5-DOF arm cannot reach arbitrary 6-DOF poses, so position is weighted above orientation and targets with more than 1 cm residual are reported as unreachable.
- **Harness** (`src/robomcp/agent/harness.py`), three modes:
  - `bare`: a plain agent loop over function calling;
  - `verify`: after the executor says it is done, a verifier sub-agent with its own context compares the scene before and after execution and can send the task back;
  - `plan`: a planner sub-agent first checks feasibility (e.g. the object does not exist) and writes steps, then execute + verify.
- **Eval** (`src/robomcp/agent/tasks.py`, `cli.py`): 5 tasks: one simple, two multi-step (one of them with a "don't move the blue cube" constraint), one reasoning ("the cube farthest from the tray"), and a trap that asks for a cube that does not exist. Success is decided by code from the scene state, never by the model's own claim.
- **Failure injection**: with probability `--slip`, a placed cube bounces out of the tray while the skill still reports success. `--slip-mode immediate` makes this visible in the tool result; `--slip-mode delayed` applies it after the tool returns, so the tool result is stale (like perception lag on a real robot).
- **Replay** (`robomcp-agent replay`): every trace logs each robot call with its full result. Replay re-runs the calls on a fresh simulator with the same seed and failure injection, checks each result against the log (MuJoCo is deterministic, so any difference means the run is not reproducible and the first divergent step is reported), re-applies the eval check, and writes a static viewer: frames, plan, tool calls and verdicts on one timeline.
- **Web console** (`robomcp-agent console`): type a task, watch the arm live (MJPEG stream), and see the plan, every tool call, and the verifier's verdict.
- `examples/`: the same agent loop before and after function calling (regex parsing vs. structured tool calls).

## Results

Gemini Flash, 5 tasks × 2 seeds = 10 runs per mode. Tokens and seconds are averages per task.

| Environment | bare | verify | plan |
|---|---|---|---|
| Ideal (no failures) | 10/10 · 7.5k tok · 10 s | 10/10 · 8.5k · 15 s | 10/10 · 8.1k · 15 s |
| Delayed silent failure (p = 0.5), verifier v1 | 5/10 | 7/10 | 8/10 |
| Delayed silent failure (p = 0.5), verifier v2 | **5/10** · 9.5k · 13 s | **10/10** · 33.9k · 32 s | **10/10** · 48.6k · 43 s |

Verifier v1 row: 2026-10-20. Other rows: 2026-10-22, after cubes were given collisions and tray slots (on 10-20, before that change, verifier v2 scored bare 6/10, verify 10/10, plan 10/10).

What the numbers say:

1. In the ideal environment every mode succeeds; extra harness layers only cost time.
2. When a failure is visible in the tool result, even `bare` recovers by itself: accurate observations let the executor verify its own work.
3. When the tool result is stale, `bare` trusts the reported success and fails; the verifier re-reads the scene and catches it, at about 3.5–5× the tokens.
4. Verifier v1 only saw the scene *after* execution. For "put the cube farthest from the tray into the tray" it re-picked the "farthest" cube among the remaining ones and rejected correct work; it also failed a correct refusal on the trap task. v2 gets the scene before and after. A wrong verifier is worse than none, because it overturns correct results.

Small sample, one model, synthetic failures: treat these as a direction, not a benchmark.

## Run

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). The harness talks to any OpenAI-compatible API: set `DEEPSEEK_API_KEY` in `.env` for DeepSeek, or `GEMINI_API_KEY` for Gemini (`LLM_PROVIDER` / `LLM_MODEL` override the choice).

```bash
uv sync

# MCP server over stdio (e.g. add it to Claude Code's .mcp.json)
uv run robomcp-server

# One task
uv run robomcp-agent run "把红色方块放进托盘" --mode plan --seed 1 --slip 0.5 --slip-mode delayed

# Eval
uv run robomcp-agent eval --modes bare,verify,plan --seeds 1,2
uv run robomcp-agent eval --modes bare,verify,plan --seeds 1,2 --slip 0.5 --slip-mode delayed

# Replay a run: step-by-step reproducibility check + viewer at out/replays/<run>/index.html
uv run robomcp-agent replay out/traces/<run>.jsonl

# Web console at http://127.0.0.1:8765
uv run robomcp-agent console
```

Traces of every run are written to `out/traces/*.jsonl`, eval results to `out/eval-*.json`.

## Credits

The SO-101 model and meshes in `src/robomcp/model/` come from [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) under the Apache License 2.0 (see `src/robomcp/model/LICENSE`); the tabletop scene is added on top.
