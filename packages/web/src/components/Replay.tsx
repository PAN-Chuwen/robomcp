"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SceneView } from "@/components/SceneView";
import { formatVec } from "@/lib/format";
import { moveStep, type Run, type RunStep, type TimelineItem } from "@/lib/run";
import { sceneViewBox } from "@/lib/scene-geometry";

const json = (v: unknown) => JSON.stringify(v);

function stepFromHash(count: number): number | null {
  const m = /^#step-(\d+)$/.exec(window.location.hash);
  return m ? Math.min(Number(m[1]), count - 1) : null;
}

/** Step-by-step replay: timeline of agent events, scrubber over env steps, top-down truth, observed-vs-truth. */
export function Replay({ run }: { run: Run }) {
  const { steps } = run;
  const [current, setCurrent] = useState(0);
  const [showHarness, setShowHarness] = useState(true);
  const timelineRef = useRef<HTMLDivElement>(null);
  const box = useMemo(() => sceneViewBox(steps.map((s) => s.truth)), [steps]);

  const select = useCallback(
    (i: number) => {
      if (i < 0 || i >= steps.length) return;
      setCurrent(i);
      window.history.replaceState(null, "", `#step-${steps[i].step}`);
    },
    [steps],
  );

  useEffect(() => {
    // Deep link (#step-N) once on load; the hash is only readable in the browser.
    const fromHash = stepFromHash(steps.length);
    const i = fromHash === null ? -1 : steps.findIndex((s) => s.step === fromHash);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (i >= 0) setCurrent(i);
  }, [steps]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      const t = ev.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      ev.preventDefault();
      select(moveStep(current, ev.key === "ArrowRight" ? 1 : -1, steps.length));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, select, steps.length]);

  useEffect(() => {
    const node = timelineRef.current?.querySelector<HTMLElement>(`[data-step-index="${current}"]`);
    node?.scrollIntoView({ block: "nearest" });
  }, [current]);

  if (steps.length === 0) {
    return (
      <div className="grid gap-4">
        <p className="pane p-4 text-muted">No episode log for this episode, so there is nothing to scrub through.</p>
        <Timeline run={run} current={-1} onSelect={() => {}} showHarness={showHarness} />
      </div>
    );
  }

  const step = steps[current];
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      <section className="pane">
        <h2 className="pane-title">
          <span>
            Truth at step {step.step} · {step.by ?? "?"} · {step.tool}
          </span>
          <span className="normal-case tracking-normal">
            {run.scored?.before === step.step && <span className="badge border-accent text-accent">scored: before</span>}
            {run.scored?.after === step.step && <span className="badge border-accent text-accent">scored: after</span>}
          </span>
        </h2>
        <SceneView truth={step.truth} diff={step.diff} box={box} />
        <Scrubber steps={steps} current={current} onSelect={select} />
        <StepDetail step={step} />
      </section>
      <section className="pane flex min-h-0 flex-col">
        <h2 className="pane-title">
          <span>Timeline</span>
          <label className="flex cursor-pointer items-center gap-1 normal-case tracking-normal">
            <input type="checkbox" checked={showHarness} onChange={(e) => setShowHarness(e.target.checked)}
              className="accent-[var(--accent)]" />
            harness calls
          </label>
        </h2>
        <div ref={timelineRef} className="lg:max-h-[calc(100dvh-220px)] lg:overflow-y-auto">
          <Timeline run={run} current={current} onSelect={select} showHarness={showHarness} />
        </div>
      </section>
    </div>
  );
}

function Scrubber({ steps, current, onSelect }: { steps: RunStep[]; current: number; onSelect: (i: number) => void }) {
  return (
    <div className="flex flex-col gap-2 border-t border-line px-3.5 py-2.5">
      <div className="flex items-center gap-2">
        <button className="btn" onClick={() => onSelect(current - 1)} disabled={current === 0} aria-label="Previous step">
          ←
        </button>
        <input
          type="range"
          min={0}
          max={steps.length - 1}
          value={current}
          onChange={(e) => onSelect(Number(e.target.value))}
          aria-label="Step"
          className="min-w-0 flex-1 accent-[var(--accent)]"
        />
        <button className="btn" onClick={() => onSelect(current + 1)} disabled={current === steps.length - 1}
          aria-label="Next step">
          →
        </button>
        <span className="font-mono text-xs whitespace-nowrap text-muted">
          {current + 1}/{steps.length}
        </span>
      </div>
      {/* one cell per env step: executor calls in the tool colour, harness calls muted, red when the agent's view
          differs from the truth or the gate blocked the action */}
      <div className="flex gap-px" role="list" aria-label="Steps">
        {steps.map((s, i) => {
          const alert = s.diff.flagged > 0 || s.diff.blocked;
          const colour = alert ? "bg-bad" : s.by === "executor" ? "bg-tool" : "bg-line";
          return (
            <button
              key={s.step}
              role="listitem"
              title={`step ${s.step} ${s.tool}${alert ? " (differs / blocked)" : ""}`}
              onClick={() => onSelect(i)}
              className={`h-3 min-w-[3px] flex-1 cursor-pointer rounded-[2px] ${colour} ${i === current ? "outline-2 outline-offset-1 outline-accent" : "opacity-80"}`}
            />
          );
        })}
      </div>
      <p className="text-[11.5px] text-muted">←/→ to step · cells: executor call, harness call, mismatch/blocked</p>
    </div>
  );
}

function StepDetail({ step }: { step: RunStep }) {
  const d = step.diff;
  return (
    <div className="border-t border-line">
      <div className="flex flex-col gap-1 px-3.5 py-2.5">
        <pre className="font-mono text-[12.5px] break-words whitespace-pre-wrap">
          {step.tool}({json(step.args)})
        </pre>
        <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
          {d.ok !== null && <span className={`badge ${d.ok ? "border-good text-good" : "border-bad text-bad"}`}>ok={String(d.ok)}</span>}
          {d.blocked && <span className="badge border-bad text-bad">blocked by safety gate</span>}
          {d.message && <span className="font-mono text-muted">{d.message}</span>}
          {d.hasScene && (
            <span className={`badge ${d.flagged ? "border-bad text-bad" : ""}`}>
              {d.flagged ? `${d.flagged} difference${d.flagged === 1 ? "" : "s"} agent saw vs truth` : "agent saw the truth"}
            </span>
          )}
        </div>
      </div>
      {d.hasScene ? (
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Object</th>
                <th>Agent saw (m)</th>
                <th>Truth (m)</th>
                <th className="num">Δ mm</th>
                <th>In tray (saw / true)</th>
              </tr>
            </thead>
            <tbody>
              {d.objects.map((o) => (
                <tr key={o.name} className={o.flagged ? "bg-bad/10" : undefined}>
                  <td>{o.name}</td>
                  <td className={o.positionDiffers || !o.observed ? "text-bad" : undefined}>
                    {o.observed ? formatVec(o.observed.position, 4) : "not seen"}
                  </td>
                  <td>{o.truth ? formatVec(o.truth.position, 4) : <span className="text-bad">does not exist</span>}</td>
                  <td className={`num ${o.positionDiffers ? "text-bad" : "text-muted"}`}>
                    {o.deltaMm === null ? "—" : o.deltaMm.toFixed(1)}
                  </td>
                  <td className={o.inTrayDiffers ? "text-bad" : undefined}>
                    {o.observed ? String(o.observed.in_tray) : "—"} / {o.truth ? String(o.truth.in_tray) : "—"}
                  </td>
                </tr>
              ))}
              <tr className={d.holding.differs ? "bg-bad/10" : undefined}>
                <td>gripper holding</td>
                <td className={d.holding.differs ? "text-bad" : undefined}>{String(d.holding.observed)}</td>
                <td>{d.holding.truth ?? "nothing"}</td>
                <td className="num text-muted">—</td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-3.5 pb-2.5 font-mono text-[12.5px] text-muted">
          The tool returned no scene{typeof step.observation === "string" ? `: ${step.observation}` : ""}; nothing to
          compare.
        </p>
      )}
    </div>
  );
}

const BORDER: Record<string, string> = {
  plan: "border-l-model",
  tool: "border-l-tool",
  say: "border-l-accent",
  pass: "border-l-good",
  fail: "border-l-bad",
};

function Timeline({ run, current, onSelect, showHarness }: {
  run: Run;
  current: number;
  onSelect: (i: number) => void;
  showHarness: boolean;
}) {
  return (
    <ol className="flex flex-col gap-1.5 p-3">
      {run.timeline.map((item, i) => {
        if (item.event.kind === "start") return null;
        if (item.event.kind === "harness_call" && !showHarness) return null;
        return <Event key={i} item={item} run={run} current={current} onSelect={onSelect} />;
      })}
    </ol>
  );
}

function Event({ item, run, current, onSelect }: {
  item: TimelineItem;
  run: Run;
  current: number;
  onSelect: (i: number) => void;
}) {
  const e = item.event;
  const target = item.stepIndex ?? item.atStep;
  const isCurrent = item.stepIndex !== null && item.stepIndex === current;
  const step = item.stepIndex !== null ? run.steps[item.stepIndex] : null;
  let kind = "";
  let border = "border-l-line";
  let body: ReactNode = null;
  let dim = false;

  switch (e.kind) {
    case "plan":
      kind = `plan · ${e.plan.feasible === false ? "infeasible" : "feasible"}`;
      border = BORDER.plan;
      body = `${e.plan.reason ?? ""}${e.plan.steps?.length ? `\n${e.plan.steps.join(" → ")}` : ""}`;
      break;
    case "tool":
      kind = "executor call";
      border = BORDER.tool;
      body = `${e.name}(${json(e.args)})${e.summary ? `\n→ ${e.summary}` : ""}`;
      break;
    case "harness_call":
      kind = "harness";
      dim = true;
      body = `${e.name}(${json(e.args)})`;
      break;
    case "say":
      kind = "executor says";
      border = BORDER.say;
      body = e.text;
      break;
    case "verify":
      kind = `verifier · ${e.verdict.passed ? "passed" : "failed"}`;
      border = e.verdict.passed ? BORDER.pass : BORDER.fail;
      body = e.verdict.reason;
      break;
    case "scored_steps":
      kind = "scored";
      body = `eval check compares step ${e.before} (before) with step ${e.after} (after)`;
      break;
    case "done":
      kind = "done";
      body = `${e.tool_calls ?? "?"} tool calls · ${e.model_calls ?? "?"} model calls · ${e.seconds ?? "?"} s · ${e.prompt_tokens ?? "?"} prompt tokens`;
      break;
    case "other":
      kind = e.original_kind;
      body = json(e.data);
      break;
  }

  const alert = step && (step.diff.flagged > 0 || step.diff.blocked);
  return (
    <li
      data-step-index={item.stepIndex ?? undefined}
      onClick={target >= 0 ? () => onSelect(target) : undefined}
      className={`rounded-lg border-l-[3px] bg-hover px-3 ${dim ? "py-0.5 opacity-60" : "py-1.5"} ${border} ${
        alert ? "border-l-bad" : ""
      } ${target >= 0 ? "cursor-pointer hover:bg-line/40" : ""} ${isCurrent ? "outline outline-1 outline-accent" : ""}`}
    >
      <div className="flex justify-between gap-2 text-[11px] tracking-[0.08em] text-muted">
        <span>{kind}</span>
        <span className="flex gap-2">
          {step?.diff.blocked && <span className="text-bad">blocked</span>}
          {step && step.diff.flagged > 0 && <span className="text-bad">≠ {step.diff.flagged}</span>}
          {step && <span>step {step.step}</span>}
        </span>
      </div>
      <pre className={`mt-0.5 font-mono break-words whitespace-pre-wrap ${dim ? "text-[11.5px]" : "text-[12.5px]"}`}>{body}</pre>
    </li>
  );
}
