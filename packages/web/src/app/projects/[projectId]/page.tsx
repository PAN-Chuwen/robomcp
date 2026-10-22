import type { Metadata } from "next";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Crumbs } from "@/components/Crumbs";
import { type ExperimentRow, ExperimentTable } from "@/components/ExperimentTable";
import { api, unwrap } from "@/lib/api/server";
import { passAt, versionLabels } from "@/lib/labels";

export const metadata: Metadata = { title: "Project" };

export default async function ProjectPage({ params }: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  const client = await api();
  const path = { params: { path: { project_id: projectId } } };
  const project = unwrap(await client.GET("/v1/projects/{project_id}", path));
  const [experiments, agents, suites] = await Promise.all([
    client.GET("/v1/projects/{project_id}/experiments", { params: { path: { project_id: projectId }, query: { limit: 200 } } }).then(unwrap),
    client.GET("/v1/projects/{project_id}/agent-versions", path).then(unwrap),
    client.GET("/v1/projects/{project_id}/suite-versions", path).then(unwrap),
  ]);
  const label = versionLabels(agents, suites);
  const rows: ExperimentRow[] = experiments.map((e) => ({
    id: e.id,
    name: e.name ?? null,
    agent: label.agent(e.agent_version_id),
    suite: label.suite(e.suite_version_id),
    status: e.status,
    created_at: e.created_at,
    repeats: e.repeats,
    seeds: e.seeds.length,
    successes: e.results.successes,
    scored: e.results.scored,
    episodes: e.results.episodes,
    rate: e.results.success_rate ?? null,
    wilson: e.results.wilson_95,
    pass1: passAt(e.results.pass_k, 1),
    passK: e.repeats > 1 ? passAt(e.results.pass_k, e.repeats) : null,
  }));
  const active = experiments.some((e) => e.status === "queued" || e.status === "running");

  return (
    <main className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 sm:px-5">
      <Crumbs items={[{ href: "/", label: "Projects" }, { label: project.name }]} />
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[17px] font-semibold">{project.name}</h1>
        <span className="meta">
          {experiments.length} experiment{experiments.length === 1 ? "" : "s"} · {agents.length} agent version
          {agents.length === 1 ? "" : "s"} · {suites.length} suite version{suites.length === 1 ? "" : "s"}
        </span>
        <AutoRefresh active={active} />
      </div>
      <section className="pane">
        <h2 className="pane-title">Experiments</h2>
        {rows.length ? (
          <ExperimentTable rows={rows} />
        ) : (
          <p className="p-4 text-muted">
            No experiments yet. Start one with <code className="font-mono">POST /v1/experiments</code>.
          </p>
        )}
      </section>
    </main>
  );
}
