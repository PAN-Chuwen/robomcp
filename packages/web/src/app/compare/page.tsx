import type { Metadata } from "next";
import Link from "next/link";
import { Crumbs } from "@/components/Crumbs";
import { Tally } from "@/components/IntervalBar";
import { StatusBadge } from "@/components/StatusBadge";
import { api, unwrap } from "@/lib/api/server";
import { verdictText } from "@/lib/compare";
import { shortId } from "@/lib/format";
import { versionLabels } from "@/lib/labels";

export const metadata: Metadata = { title: "Comparison" };

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
const TONE = { bad: "border-bad text-bad", good: "border-good text-good", muted: "border-line text-fg" };

export default async function ComparePage({ searchParams }: PageProps<"/compare">) {
  const sp = await searchParams;
  const baseline = first(sp.baseline);
  const candidate = first(sp.candidate);
  if (!baseline || !candidate) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-5">
        <p className="text-muted">
          Pick two experiments on a project page, or open <code className="font-mono">/compare?baseline=…&candidate=…</code>.
        </p>
      </main>
    );
  }

  const client = await api();
  const get = (id: string) => client.GET("/v1/experiments/{experiment_id}", { params: { path: { experiment_id: id } } }).then(unwrap);
  const [a, b] = await Promise.all([get(baseline), get(candidate)]);
  const res = await client.GET("/v1/experiments/compare", { params: { query: { baseline, candidate } } });
  if (res.response.status === 422) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-5">
        <p role="alert" className="text-bad">
          These experiments cannot be compared: {String((res.error as { detail?: unknown })?.detail ?? "invalid pair")}.
        </p>
      </main>
    );
  }
  const c = unwrap(res);
  const projectPath = { params: { path: { project_id: a.project_id } } };
  const [project, agents, suites] = await Promise.all([
    client.GET("/v1/projects/{project_id}", projectPath).then(unwrap),
    client.GET("/v1/projects/{project_id}/agent-versions", projectPath).then(unwrap),
    client.GET("/v1/projects/{project_id}/suite-versions", projectPath).then(unwrap),
  ]);
  const label = versionLabels(agents, suites);
  const v = verdictText(c);
  const name = (e: typeof a) => e.name ?? shortId(e.id);

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-5 sm:px-5">
      <Crumbs
        items={[
          { href: "/", label: "Projects" },
          { href: `/projects/${project.id}`, label: project.name },
          { label: `${name(a)} → ${name(b)}` },
        ]}
      />

      <section className={`rounded-[10px] border bg-panel px-4 py-3 ${TONE[v.tone]}`}>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-[17px] font-semibold">{v.title}</h1>
          <span className="font-mono text-[13px]">
            candidate {name(b)} vs baseline {name(a)}
          </span>
        </div>
        <p className="mt-1 font-mono text-[12.5px] text-fg">{v.detail}</p>
        <p className="mt-1 text-[12.5px] text-muted">
          Episodes are paired on (task, seed, repeat); only discordant pairs, where exactly one side succeeded, are
          evidence of a difference.
        </p>
      </section>

      {!c.same_suite_version && (
        <p role="alert" className="rounded-[10px] border border-tool px-4 py-2 text-[13px] text-tool">
          The two experiments ran different suite versions ({label.suite(a.suite_version_id)} vs{" "}
          {label.suite(b.suite_version_id)}): tasks with the same key may differ, so pairs are not like-for-like.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <section className="pane">
          <h2 className="pane-title">Paired outcomes</h2>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th />
                  <th className="num">candidate ✓</th>
                  <th className="num">candidate ✗</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th>baseline ✓</th>
                  <td className="num">{c.both}</td>
                  <td className={`num ${c.only_baseline ? "font-semibold text-bad" : ""}`}>{c.only_baseline}</td>
                </tr>
                <tr>
                  <th>baseline ✗</th>
                  <td className={`num ${c.only_candidate ? "font-semibold text-good" : ""}`}>{c.only_candidate}</td>
                  <td className="num">{c.neither}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="border-t border-line px-3 py-2 font-mono text-[12.5px] text-muted">
            {c.pairs} pairs · {c.unpaired} unpaired (scored in only one experiment, left out of the test)
          </p>
        </section>

        <section className="pane">
          <h2 className="pane-title">Experiments</h2>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Experiment</th>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Successes / scored · Wilson 95%</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["baseline", a],
                    ["candidate", b],
                  ] as const
                ).map(([role, x]) => {
                  return (
                    <tr key={role}>
                      <td className="text-muted">{role}</td>
                      <td>
                        <Link href={`/experiments/${x.id}`} className="link">
                          {name(x)}
                        </Link>
                      </td>
                      <td>{label.agent(x.agent_version_id)}</td>
                      <td>
                        <StatusBadge status={x.status} />
                      </td>
                      <td>
                        <Tally successes={x.results.successes} scored={x.results.scored}
                          rate={x.results.success_rate ?? null} wilson={x.results.wilson_95} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="border-t border-line px-3 py-2 text-[12.5px]">
            <Link className="link" href={`/compare?baseline=${b.id}&candidate=${a.id}`}>
              Swap baseline and candidate
            </Link>
          </p>
        </section>
      </div>

      <section className="pane">
        <h2 className="pane-title">Per task</h2>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Task</th>
                <th className="num">both ✓</th>
                <th className="num">only baseline ✓</th>
                <th className="num">only candidate ✓</th>
                <th className="num">neither</th>
                <th className="num">pairs</th>
              </tr>
            </thead>
            <tbody>
              {c.per_task.map((t) => (
                <tr key={t.task_key}>
                  <td>{t.task_key}</td>
                  <td className="num">{t.both}</td>
                  <td className={`num ${t.only_baseline ? "text-bad" : "text-muted"}`}>{t.only_baseline}</td>
                  <td className={`num ${t.only_candidate ? "text-good" : "text-muted"}`}>{t.only_candidate}</td>
                  <td className="num">{t.neither}</td>
                  <td className="num">{t.both + t.only_baseline + t.only_candidate + t.neither}</td>
                </tr>
              ))}
              {c.per_task.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-muted">
                    No paired episodes yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
