import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Crumbs } from "@/components/Crumbs";
import { StatusBadge } from "@/components/StatusBadge";
import { TallyTable } from "@/components/TallyTable";
import { api, unwrap } from "@/lib/api/server";
import { formatDate, formatMetric, pct, shortId } from "@/lib/format";
import { versionLabels } from "@/lib/labels";

export const metadata: Metadata = { title: "Experiment" };

const PAGE = 50;
const FILTERS = ["queued", "running", "succeeded", "failed", "error"] as const;
type Filter = (typeof FILTERS)[number];
const METRICS = ["tool_calls", "prompt_tokens", "blocked_actions", "seconds"] as const;

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export default async function ExperimentPage({ params, searchParams }: PageProps<"/experiments/[experimentId]">) {
  const { experimentId } = await params;
  const sp = await searchParams;
  const status = FILTERS.find((f) => f === first(sp.status)) as Filter | undefined;
  const offset = Math.max(0, Number.parseInt(first(sp.offset) ?? "0", 10) || 0);

  const client = await api();
  const e = unwrap(await client.GET("/v1/experiments/{experiment_id}", { params: { path: { experiment_id: experimentId } } }));
  const projectPath = { params: { path: { project_id: e.project_id } } };
  const [project, agents, suites, page] = await Promise.all([
    client.GET("/v1/projects/{project_id}", projectPath).then(unwrap),
    client.GET("/v1/projects/{project_id}/agent-versions", projectPath).then(unwrap),
    client.GET("/v1/projects/{project_id}/suite-versions", projectPath).then(unwrap),
    client
      .GET("/v1/experiments/{experiment_id}/episodes", {
        params: { path: { experiment_id: experimentId }, query: { status, limit: PAGE, offset } },
      })
      .then(unwrap),
  ]);
  const label = versionLabels(agents, suites);
  const r = e.results;
  const active = e.status === "queued" || e.status === "running";
  const href = (q: { status?: string; offset?: number }) => {
    const u = new URLSearchParams();
    if (q.status) u.set("status", q.status);
    if (q.offset) u.set("offset", String(q.offset));
    const s = u.toString();
    return `/experiments/${experimentId}${s ? `?${s}` : ""}`;
  };

  return (
    <main className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 sm:px-5">
      <Crumbs
        items={[
          { href: "/", label: "Projects" },
          { href: `/projects/${project.id}`, label: project.name },
          { label: e.name ?? shortId(e.id) },
        ]}
      />
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[17px] font-semibold">{e.name ?? shortId(e.id)}</h1>
          <StatusBadge status={e.status} />
          <AutoRefresh active={active} />
        </div>
        <div className="meta">
          agent {label.agent(e.agent_version_id)} · suite {label.suite(e.suite_version_id)} · {e.seeds.length} seed
          {e.seeds.length === 1 ? "" : "s"} [{e.seeds.slice(0, 12).join(", ")}
          {e.seeds.length > 12 ? ", …" : ""}] × {e.repeats} repeat{e.repeats === 1 ? "" : "s"} · created{" "}
          {formatDate(e.created_at)}
          {e.finished_at ? ` · finished ${formatDate(e.finished_at)}` : ""} · {e.id}
        </div>
      </header>

      <section className="pane">
        <h2 className="pane-title">
          <span>Results</span>
          <span className="normal-case tracking-normal">error episodes are excluded from the scored count</span>
        </h2>
        <TallyTable overall={r} perTask={r.per_task} />
      </section>

      {e.repeats > 1 && r.pass_k.length > 0 && (
        <section className="pane">
          <h2 className="pane-title">
            <span>pass^k</span>
            <span className="normal-case tracking-normal">
              probability all k repeats on the same (task, seed) succeed
            </span>
          </h2>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="num">k</th>
                  <th className="num">pass^k</th>
                  <th className="num">(task, seed) groups</th>
                </tr>
              </thead>
              <tbody>
                {r.pass_k.map((p) => (
                  <tr key={p.k}>
                    <td className="num">{p.k}</td>
                    <td className="num">{pct(p.value, 1)}</td>
                    <td className="num">{p.groups}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="pane">
        <h2 className="pane-title">
          <span>Episodes</span>
          <span className="flex flex-wrap gap-1.5 normal-case tracking-normal">
            <Link href={href({})} className={`badge ${!status ? "border-accent text-accent" : ""}`}>
              all {r.episodes}
            </Link>
            {FILTERS.map((f) => (
              <Link key={f} href={href({ status: f })} className={`badge ${status === f ? "border-accent text-accent" : ""}`}>
                {f} {r.by_status[f] ?? 0}
              </Link>
            ))}
          </span>
        </h2>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Task</th>
                <th className="num">Seed</th>
                <th className="num">Repeat</th>
                <th>Status</th>
                {METRICS.map((m) => (
                  <th key={m} className="num">
                    {m}
                  </th>
                ))}
                <th className="num">Attempts</th>
                <th>Episode</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((ep) => (
                <tr key={ep.id}>
                  <td>{ep.task_key}</td>
                  <td className="num">{ep.seed}</td>
                  <td className="num">{ep.repeat_index}</td>
                  <td>
                    <StatusBadge status={ep.status} />
                  </td>
                  {METRICS.map((m) => (
                    <td key={m} className={`num ${m === "blocked_actions" && Number(ep.metrics?.[m]) > 0 ? "text-bad" : ""}`}>
                      {formatMetric(ep.metrics?.[m])}
                    </td>
                  ))}
                  <td className="num">{ep.attempts}</td>
                  <td>
                    <Link href={`/episodes/${ep.id}`} className="link">
                      replay {shortId(ep.id)}
                    </Link>
                    {ep.error && (
                      <span className="ml-2 text-bad" title={ep.error}>
                        {ep.error.slice(0, 60)}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
              {page.items.length === 0 && (
                <tr>
                  <td colSpan={5 + METRICS.length + 1} className="text-muted">
                    No episodes{status ? ` with status ${status}` : ""}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t border-line px-3 py-2 text-[12.5px] text-muted">
          <span>
            {page.total === 0 ? 0 : offset + 1}–{Math.min(offset + page.items.length, page.total)} of {page.total}
          </span>
          {offset > 0 && (
            <Link className="btn" href={href({ status, offset: Math.max(0, offset - PAGE) })}>
              ← Previous
            </Link>
          )}
          {offset + PAGE < page.total && (
            <Link className="btn" href={href({ status, offset: offset + PAGE })}>
              Next →
            </Link>
          )}
        </div>
      </section>
    </main>
  );
}
