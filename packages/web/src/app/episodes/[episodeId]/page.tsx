import type { Metadata } from "next";
import { Crumbs } from "@/components/Crumbs";
import { Replay } from "@/components/Replay";
import { StatusBadge } from "@/components/StatusBadge";
import { api, getArtifact, unwrap } from "@/lib/api/server";
import { formatDate, formatMetric, shortId } from "@/lib/format";
import { joinRun } from "@/lib/run";

export const metadata: Metadata = { title: "Episode replay" };

const METRICS = ["tool_calls", "model_calls", "prompt_tokens", "cache_hit_tokens", "blocked_actions", "verifier_rounds", "seconds"];

export default async function EpisodePage({ params }: PageProps<"/episodes/[episodeId]">) {
  const { episodeId } = await params;
  const client = await api();
  const ep = unwrap(await client.GET("/v1/episodes/{episode_id}", { params: { path: { episode_id: episodeId } } }));
  const [experiment, trace, log] = await Promise.all([
    client.GET("/v1/experiments/{experiment_id}", { params: { path: { experiment_id: ep.experiment_id } } }).then(unwrap),
    ep.trace_uri ? getArtifact(client, episodeId, "trace") : null,
    ep.episode_log_uri ? getArtifact(client, episodeId, "episode_log") : null,
  ]);
  const project = unwrap(await client.GET("/v1/projects/{project_id}", { params: { path: { project_id: experiment.project_id } } }));
  const run = joinRun(trace, log);
  const s = run.start;
  const m = ep.metrics ?? {};
  const fingerprint = (run.header?.fingerprint ?? (m.fingerprint as Record<string, string> | undefined)) || {};

  return (
    <main className="mx-auto flex max-w-[1500px] flex-col gap-4 px-4 py-5 sm:px-5">
      <Crumbs
        items={[
          { href: "/", label: "Projects" },
          { href: `/projects/${project.id}`, label: project.name },
          { href: `/experiments/${experiment.id}`, label: experiment.name ?? shortId(experiment.id) },
          { label: `${ep.task_key} · seed ${ep.seed} · repeat ${ep.repeat_index}` },
        ]}
      />
      <header className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[17px] font-semibold">{s?.goal || ep.task_key}</h1>
          <StatusBadge status={ep.status} />
          {run.lastVerdict && (
            <span
              className={`badge ${run.lastVerdict.passed === (ep.success ?? run.lastVerdict.passed) ? "border-good text-good" : "border-bad text-bad"}`}
              title="last verifier verdict; red when it contradicts the eval check"
            >
              verifier {run.lastVerdict.passed ? "passed" : "failed"}
            </span>
          )}
        </div>
        <div className="meta">
          {s ? `mode ${s.mode} · seed ${s.seed ?? "none"} · slip ${s.slip} ${s.slip_mode ?? ""} · ${s.model ?? ""} · ` : ""}
          perception {run.header?.perception ?? "?"} · MuJoCo {run.header?.mujoco ?? s?.mujoco ?? "?"}
          {Object.keys(fingerprint).length > 0 &&
            ` · fingerprint ${Object.entries(fingerprint).map(([k, v]) => `${k}=${v}`).join(" ")}`}
        </div>
        <div className="meta">
          {METRICS.filter((k) => k in m).map((k) => `${k} ${formatMetric(m[k])}`).join(" · ")}
          {ep.started_at && ` · started ${formatDate(ep.started_at)}`} · attempt {ep.attempts} · {ep.id}
        </div>
        {ep.error && <p className="font-mono text-[12.5px] text-bad">{ep.error}</p>}
        {run.warnings.length > 0 && (
          <ul className="font-mono text-[12.5px] text-tool">
            {run.warnings.map((w) => (
              <li key={w}>⚠ {w}</li>
            ))}
          </ul>
        )}
      </header>
      {trace === null && log === null ? (
        <p className="pane p-4 text-muted">
          This episode has no artifacts yet ({ep.status}). Traces and episode logs are uploaded when an episode finishes.
        </p>
      ) : (
        <Replay run={run} />
      )}
    </main>
  );
}
