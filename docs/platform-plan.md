# Platform plan: hosted evaluation and observability for embodied agents

RoboMCP grows from a single-machine demo into a self-hostable SaaS (docker compose) with a public demo:
teams connect their own agent harness to hosted simulation episodes over MCP, and the platform generates
scenes, injects failures, replays runs, computes statistics, attributes failures, and gates regressions.

## Workflow

1. **Suite**: versioned tasks, each with a goal, a scene generator, a success check and perturbations.
2. **Agent**: a hosted harness template (model + prompts), or bring-your-own agent that connects to a
   per-episode MCP endpoint with a token.
3. **Experiment**: agent version × suite version × seeds × k repeats, queued and run by sim workers.
4. **Results**: success rate with confidence interval, pass^k, paired comparison against a baseline on the
   same seeds; every episode can be replayed step by step.
5. **Attribution**: failures are labelled perception / planning / execution / verifier / safety from
   ground truth; failed episodes can be added to the regression suite.

## Architecture

```
Web (Next.js) ──► API (FastAPI) ──► Postgres (Alembic): metadata, scores, job queue (SKIP LOCKED)
                       │                  └─ S3 / MinIO: frames, videos, raw traces
SDK / CLI / CI gate ───┘
                                 ▼ claims jobs
                 Sim worker (one process per episode: MuJoCo renders on the main thread)
                 ├─ environment: MuJoCo + skills + safety gate + perception, served over MCP
                 ├─ hosted harness (optional; external agents connect instead)
                 └─ model gateway: BYOK, token metering, recorded LLM responses for replay
```

## Design points

1. **Reproducibility.** An episode is fingerprinted by image digest, model-file hash, MuJoCo version,
   scene seed, perturbation seed and agent version. Non-deterministic inputs (LLM replies, detector
   outputs) are recorded and injected on replay.
2. **Observation vs ground truth.** Agents and verifiers only see observations; ground truth is used for
   scoring, replay checks and attribution. The environment records truth itself, so an external agent
   cannot leak or fake it.
3. **Statistics.** Paired comparisons on the same seeds (McNemar / paired bootstrap), pass^k, Wilson
   intervals. A gate fails only on a significant paired regression.
4. **Feasible scenes only.** Generated scenes are first solved by a scripted oracle (ground truth + skills);
   scenes the oracle cannot solve are discarded, so every failure belongs to the agent.
5. **Safety gate.** Deterministic checks (workspace, table clearance, reach) between the agent's command
   and execution; blocked actions are counted as a metric.
6. **Failure attribution.** Find the first step where the agent's belief departs from ground truth:
   localisation error above the grasp tolerance → perception; wrong target chosen → planning; correct
   target and estimate but no grasp → execution; verdict contradicting truth → verifier.
7. **Worker scheduling.** One process per episode; episodes mostly wait on the LLM, so many run
   concurrently. Rendering is rate-limited, and each worker pins its own EGL device.
8. **Multi-tenancy.** `org_id` on every row plus Postgres row-level security; API keys stored hashed;
   BYOK model keys encrypted at rest; metering of sim minutes and storage with quotas.

## Measured mechanisms (2026-10-22)

These decide what the environment must model; probes in `scripts/`.

| Mechanism | Measurement | Consequence |
|---|---|---|
| Grasp position tolerance | succeeds within 6 mm; tangential 9 mm misses; radial asymmetric (+9 mm outward misses, −15 mm inward holds) | perception error budget is about 6 mm |
| Cube orientation | no effect: closing jaws rotate the cube into line (−45° → 22°) | gripper-angle choice needs elongated objects |
| Top camera | 1.29 mm/px at 640×480, a cube is ~20×20 px; the target is fully occluded while hovering above it | look only after retracting, or add a wrist camera |
| Injected slip | random, independent of the agent's action | blind retry is optimal; replanning needs failures with a cause |
| Skill results | return the full ground-truth scene | the agent and verifier currently read truth |
| Perception difficulty | single-colour cubes on a plain table are trivial to threshold | a VLM earns its place on semantics, geometry comes from depth |

## Milestones

- **M0** (this repo): observation/truth split, grasp success from gripper opening, safety gate,
  environment fingerprint.
- **M1** platform skeleton: monorepo `packages/{env,harness,api,worker,web}`, docker compose, Alembic,
  orgs / projects / API keys, experiment → episode queue, traces and frames stored.
- **M2** web app: experiments and comparisons, episode replay, statistics.
- **M3** bring-your-own agent: per-episode MCP endpoint, Python SDK, CLI gate, GitHub Action.
- **M4** scenarios: perception modes (oracle / VLM), scene generator with feasibility check, attribution.
- **M5** launch: public demo, metering and quotas, audit log, OpenTelemetry, rate limits.

Out of scope: payments (metering only), real-robot fleet management, training VLAs (the execution
layer keeps an interface for one).

## Decisions

- Self-hostable with docker compose plus one public demo, not open sign-up.
- Next.js + TypeScript web app; GitHub OAuth login, organisations and roles built in-house.
- Evolve this repository into the monorepo.

## References

Gemini Robotics-ER 1.5 (planner calling a VLA); π0.5 / GR00T N1 (System 2 / System 1); LERa and
arXiv 2602.13081 / 2607.06990 (closed-loop replanning from world-state checks); SafeEmbodAI, RoboGuard
(safety gates); arXiv 2603.07866, HiFi-CS (VLM grounding + depth back-projection); LangSmith, Braintrust
(datasets, experiments, trace-to-dataset); τ-bench (pass^k); RoboArena (pairwise ranking); SimplerEnv
(sim–real correlation); dm_control EGL notes (GPU contention across render workers).
