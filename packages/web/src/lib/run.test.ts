import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { joinRun, moveStep, parseJsonl, toTraceEvent } from "./run";

// A real bare-mode run (seed 1, delayed slip 0.5) as stored by the platform worker.
const fixture = (name: string) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8");
const TRACE = fixture("bare-seed1.trace.jsonl");
const LOG = fixture("bare-seed1.env.jsonl");

describe("parseJsonl", () => {
  it("skips blank lines and reports unparsable ones with their line number", () => {
    const { records, errors } = parseJsonl('{"a":1}\n\n{oops\n{"b":2}\n');
    expect(records).toEqual([{ a: 1 }, { b: 2 }]);
    expect(errors).toHaveLength(1);
    expect(errors[0].line).toBe(3);
  });
});

describe("toTraceEvent", () => {
  it("keeps unknown kinds as other events", () => {
    expect(toTraceEvent({ kind: "recording", info: "x" })).toEqual({
      kind: "other", original_kind: "recording", data: { info: "x" },
    });
  });

  it("rejects a robot call without a step", () => {
    expect(() => toTraceEvent({ kind: "tool", name: "pick", args: {} })).toThrow(/step/);
  });
});

describe("joinRun", () => {
  const run = joinRun(TRACE, LOG);

  it("reads the start event and the episode header", () => {
    expect(run.start).toMatchObject({ goal: "把红色方块放进托盘", mode: "bare", seed: 1, slip: 0.5,
      slip_mode: "delayed", trace_version: 3 });
    expect(run.header).toMatchObject({ perception: "oracle", slip_mode: "delayed", mujoco: "3.15.0" });
    expect(run.warnings).toEqual([]);
  });

  it("attributes every env step to the executor or the harness via its step number", () => {
    expect(run.steps.map((s) => [s.step, s.tool, s.by])).toEqual([
      [0, "reset_scene", "harness"],
      [1, "get_scene", "harness"],
      [2, "get_scene", "executor"],
      [3, "pick", "executor"],
      [4, "place_in_tray", "executor"],
      [5, "get_scene", "harness"],
    ]);
  });

  it("links robot-call events to their step and places other events after the latest step", () => {
    const pick = run.timeline.find((t) => t.event.kind === "tool" && t.event.name === "pick")!;
    expect(pick.stepIndex).toBe(3);
    expect(run.steps[3].events).toEqual([run.timeline.indexOf(pick)]);
    const say = run.timeline.find((t) => t.event.kind === "say")!;
    expect(say.stepIndex).toBeNull();
    expect(say.atStep).toBe(4);
    expect(run.timeline[0]).toMatchObject({ stepIndex: null, atStep: -1 }); // start
  });

  it("exposes the scored steps and the done summary", () => {
    expect(run.scored).toEqual({ before: 1, after: 5 });
    expect(run.done).toMatchObject({ tool_calls: 3, model_calls: 4, prompt_tokens: 5370, seconds: 10 });
    expect(run.lastVerdict).toBeNull(); // bare mode has no verifier
  });

  it("works with only one artifact", () => {
    const traceOnly = joinRun(TRACE, null);
    expect(traceOnly.steps).toEqual([]);
    expect(traceOnly.timeline).toHaveLength(10);
    expect(traceOnly.warnings).toEqual([]);
    const logOnly = joinRun(null, LOG);
    expect(logOnly.steps).toHaveLength(6);
    expect(logOnly.steps.every((s) => s.by === null)).toBe(true);
    expect(logOnly.warnings).toEqual([]);
  });

  it("warns when the two sides disagree", () => {
    const extra = TRACE + JSON.stringify({ kind: "tool", name: "go_home", args: {}, summary: "", step: 9 }) + "\n";
    const firstSteps = LOG.split("\n").slice(0, 4).join("\n"); // header + steps 0..2
    const run = joinRun(extra, firstSteps);
    expect(run.warnings).toContain("go_home (step 9) has no episode-log record");
    expect(run.warnings.some((w) => w.includes("pick (step 3)"))).toBe(true);
  });

  it("warns about traces older than v3 and malformed lines", () => {
    const run = joinRun('{"kind":"start","goal":"g","mode":"bare"}\nnot json\n', null);
    expect(run.warnings).toHaveLength(2);
    expect(run.warnings[0]).toMatch(/^trace line 2: /);
    expect(run.warnings[1]).toBe("trace v1 has no step numbers");
  });
});

describe("moveStep", () => {
  it("clamps to the run", () => {
    expect(moveStep(0, -1, 6)).toBe(0);
    expect(moveStep(5, 1, 6)).toBe(5);
    expect(moveStep(2, 1, 6)).toBe(3);
    expect(moveStep(0, 1, 0)).toBe(-1);
  });
});
