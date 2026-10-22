// Parsing and joining of one run: the agent's trace (v3) and the environment's episode log.
//
// The trace is the agent's account (plan, tool calls, verdicts); the episode log is the environment's record of
// every robot call with what the agent saw (`observation`) and the ground truth (`truth`). Robot calls in the
// trace carry `step`, the index of the matching episode-log record, which is how the two are joined.

import { diffObservation, type Scene, type StepDiff } from "./diff";

export interface JsonlResult {
  records: unknown[];
  errors: { line: number; message: string }[];
}

/** Parse JSON lines; blank lines are skipped, unparsable lines are reported instead of thrown. */
export function parseJsonl(text: string): JsonlResult {
  const records: unknown[] = [];
  const errors: JsonlResult["errors"] = [];
  text.split("\n").forEach((raw, i) => {
    const line = raw.trim();
    if (!line) return;
    try {
      records.push(JSON.parse(line));
    } catch (e) {
      errors.push({ line: i + 1, message: e instanceof Error ? e.message : String(e) });
    }
  });
  return { records, errors };
}

// --- trace v3 ------------------------------------------------------------------------------------------------

type Args = Record<string, unknown>;

export interface StartEvent {
  kind: "start";
  goal: string;
  mode: string;
  seed: number | null;
  slip: number;
  slip_mode: string | null;
  episode_log: string | null;
  model: string | null;
  mujoco: string | null;
  trace_version: number;
}
export interface PlanEvent {
  kind: "plan";
  plan: { feasible?: boolean; reason?: string; steps?: string[] };
}
export interface ToolEvent {
  kind: "tool";
  name: string;
  args: Args;
  summary: string;
  step: number;
}
export interface HarnessCallEvent {
  kind: "harness_call";
  name: string;
  args: Args;
  step: number;
}
export interface SayEvent {
  kind: "say";
  text: string;
}
export interface VerifyEvent {
  kind: "verify";
  verdict: { passed: boolean; reason: string };
}
export interface ScoredStepsEvent {
  kind: "scored_steps";
  before: number;
  after: number;
}
export interface DoneEvent {
  kind: "done";
  final: string;
  tool_calls: number | null;
  model_calls: number | null;
  seconds: number | null;
  prompt_tokens: number | null;
  cache_hit_rate: number | null;
}
/** A kind this viewer does not know (e.g. "recording"); kept so the timeline shows it. */
export interface OtherEvent {
  kind: "other";
  original_kind: string;
  data: Args;
}

export type TraceEvent =
  | StartEvent
  | PlanEvent
  | ToolEvent
  | HarnessCallEvent
  | SayEvent
  | VerifyEvent
  | ScoredStepsEvent
  | DoneEvent
  | OtherEvent;

const isObj = (v: unknown): v is Args => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const args = (v: unknown): Args => (isObj(v) ? v : {});

/** Normalise one trace record; throws on a record that claims a known kind but lacks its required fields. */
export function toTraceEvent(r: unknown): TraceEvent {
  if (!isObj(r) || typeof r.kind !== "string") throw new Error("record has no kind");
  const step = num(r.step);
  switch (r.kind) {
    case "start":
      return {
        kind: "start",
        goal: str(r.goal) ?? "",
        mode: str(r.mode) ?? "?",
        seed: num(r.seed),
        slip: num(r.slip) ?? 0,
        slip_mode: str(r.slip_mode),
        episode_log: str(r.episode_log),
        model: str(r.model),
        mujoco: str(r.mujoco),
        trace_version: num(r.trace_version) ?? 1,
      };
    case "plan":
      return { kind: "plan", plan: isObj(r.plan) ? (r.plan as PlanEvent["plan"]) : {} };
    case "tool":
    case "harness_call":
      if (step === null) throw new Error(`${r.kind} event without step`);
      return r.kind === "tool"
        ? { kind: "tool", name: str(r.name) ?? "?", args: args(r.args), summary: str(r.summary) ?? "", step }
        : { kind: "harness_call", name: str(r.name) ?? "?", args: args(r.args), step };
    case "say":
      return { kind: "say", text: str(r.text) ?? "" };
    case "verify": {
      const v = isObj(r.verdict) ? r.verdict : {};
      return { kind: "verify", verdict: { passed: v.passed === true, reason: str(v.reason) ?? "" } };
    }
    case "scored_steps": {
      const before = num(r.before), after = num(r.after);
      if (before === null || after === null) throw new Error("scored_steps without before/after");
      return { kind: "scored_steps", before, after };
    }
    case "done":
      return {
        kind: "done",
        final: str(r.final) ?? "",
        tool_calls: num(r.tool_calls),
        model_calls: num(r.model_calls),
        seconds: num(r.seconds),
        prompt_tokens: num(r.prompt_tokens),
        cache_hit_rate: num(r.cache_hit_rate),
      };
    default: {
      const { kind, ...data } = r;
      return { kind: "other", original_kind: kind as string, data };
    }
  }
}

// --- episode log ---------------------------------------------------------------------------------------------

export interface EpisodeHeader {
  slip: number;
  slip_mode: string | null;
  perception: string | null;
  mujoco: string | null;
  fingerprint: Record<string, string>;
}

export interface EnvStep {
  step: number;
  tool: string;
  args: Args;
  observation: unknown; // what the agent saw: a skill result {ok, message, scene, blocked?}, a scene, or a string
  truth: Scene;
}

function isScene(v: unknown): v is Scene {
  return isObj(v) && Array.isArray(v.objects) && isObj(v.tray) && isObj(v.gripper);
}

// --- joined run ----------------------------------------------------------------------------------------------

export interface RunStep extends EnvStep {
  by: "executor" | "harness" | null; // who issued the call, from the trace; null when no trace event has this step
  events: number[]; // indices into Run.timeline of events with this step
  diff: StepDiff;
}

export interface TimelineItem {
  event: TraceEvent;
  /** Index into Run.steps of this event's own env step (robot calls only). */
  stepIndex: number | null;
  /** Index into Run.steps of the latest env step at or before this event; -1 before the first robot call. */
  atStep: number;
}

export interface Run {
  start: StartEvent | null;
  header: EpisodeHeader | null;
  steps: RunStep[];
  timeline: TimelineItem[];
  scored: { before: number; after: number } | null; // env step numbers the eval check compared
  done: DoneEvent | null;
  lastVerdict: VerifyEvent["verdict"] | null;
  warnings: string[];
}

/** Join a trace and an episode log (both raw JSONL text; either may be null when the artifact is missing). */
export function joinRun(traceText: string | null, logText: string | null): Run {
  const warnings: string[] = [];

  const events: TraceEvent[] = [];
  if (traceText !== null) {
    const { records, errors } = parseJsonl(traceText);
    errors.forEach((e) => warnings.push(`trace line ${e.line}: ${e.message}`));
    records.forEach((r, i) => {
      try {
        events.push(toTraceEvent(r));
      } catch (e) {
        warnings.push(`trace record ${i + 1}: ${(e as Error).message}`);
      }
    });
  }
  const start = events[0]?.kind === "start" ? events[0] : null;
  if (traceText !== null && !start) warnings.push("trace does not begin with a start event");
  if (start && start.trace_version < 3) warnings.push(`trace v${start.trace_version} has no step numbers`);

  let header: EpisodeHeader | null = null;
  const envSteps: EnvStep[] = [];
  if (logText !== null) {
    const { records, errors } = parseJsonl(logText);
    errors.forEach((e) => warnings.push(`episode log line ${e.line}: ${e.message}`));
    records.forEach((r, i) => {
      if (!isObj(r)) return warnings.push(`episode log record ${i + 1} is not an object`);
      if (r.kind === "episode") {
        header = {
          slip: num(r.slip) ?? 0,
          slip_mode: str(r.slip_mode),
          perception: str(r.perception),
          mujoco: str(r.mujoco),
          fingerprint: isObj(r.fingerprint) ? (r.fingerprint as Record<string, string>) : {},
        };
      } else if (r.kind === "step") {
        const step = num(r.step);
        if (step === null || !isScene(r.truth)) return warnings.push(`episode log record ${i + 1}: malformed step`);
        envSteps.push({ step, tool: str(r.tool) ?? "?", args: args(r.args), observation: r.observation, truth: r.truth });
      }
    });
    if (!header) warnings.push("episode log has no episode header");
  }
  envSteps.sort((a, b) => a.step - b.step);

  const indexOfStep = new Map(envSteps.map((s, i) => [s.step, i]));
  const steps: RunStep[] = envSteps.map((s) => ({
    ...s,
    by: null,
    events: [],
    diff: diffObservation(s.observation, s.truth),
  }));

  const timeline: TimelineItem[] = [];
  let atStep = -1;
  for (const event of events) {
    let stepIndex: number | null = null;
    if (event.kind === "tool" || event.kind === "harness_call") {
      const i = indexOfStep.get(event.step);
      if (i === undefined) {
        if (logText !== null) warnings.push(`${event.name} (step ${event.step}) has no episode-log record`);
      } else {
        stepIndex = i;
        atStep = i;
        steps[i].by = event.kind === "tool" ? "executor" : "harness";
        steps[i].events.push(timeline.length);
      }
    }
    timeline.push({ event, stepIndex, atStep });
  }
  if (traceText !== null) {
    const orphans = steps.filter((s) => s.by === null).map((s) => s.step);
    if (orphans.length) warnings.push(`episode-log steps without a trace event: ${orphans.join(", ")}`);
  }

  const scoredEvent = events.find((e): e is ScoredStepsEvent => e.kind === "scored_steps");
  const verdicts = events.filter((e): e is VerifyEvent => e.kind === "verify");
  return {
    start,
    header,
    steps,
    timeline,
    scored: scoredEvent ? { before: scoredEvent.before, after: scoredEvent.after } : null,
    done: events.find((e): e is DoneEvent => e.kind === "done") ?? null,
    lastVerdict: verdicts.length ? verdicts[verdicts.length - 1].verdict : null,
    warnings,
  };
}

/** Next step index for ←/→ navigation, clamped to the run. */
export function moveStep(current: number, delta: number, count: number): number {
  if (count === 0) return -1;
  return Math.min(Math.max(current + delta, 0), count - 1);
}
