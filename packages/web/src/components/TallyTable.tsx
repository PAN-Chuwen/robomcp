import { Tally } from "@/components/IntervalBar";

interface TallyLike {
  episodes: number;
  by_status: Record<string, number>;
  successes: number;
  scored: number;
  success_rate?: number | null;
  wilson_95: number[];
}

const STATUSES = ["queued", "running", "succeeded", "failed", "error"] as const;

/** Overall + per-task tallies: successes over scored episodes with the Wilson 95% interval, plus status counts. */
export function TallyTable({ overall, perTask }: { overall: TallyLike; perTask: (TallyLike & { task_key: string })[] }) {
  const row = (label: string, t: TallyLike, strong = false) => (
    <tr key={label} className={strong ? "font-semibold" : undefined}>
      <td>{label}</td>
      <td>
        <Tally successes={t.successes} scored={t.scored} rate={t.success_rate ?? null} wilson={t.wilson_95} />
      </td>
      {STATUSES.map((s) => (
        <td key={s} className={`num ${t.by_status[s] ? "" : "text-muted"}`}>
          {t.by_status[s] ?? 0}
        </td>
      ))}
      <td className="num">{t.episodes}</td>
    </tr>
  );
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead>
          <tr>
            <th>Task</th>
            <th>Successes / scored · Wilson 95%</th>
            {STATUSES.map((s) => (
              <th key={s} className="num">
                {s}
              </th>
            ))}
            <th className="num">episodes</th>
          </tr>
        </thead>
        <tbody>
          {row("all tasks", overall, true)}
          {perTask.map((t) => row(t.task_key, t))}
        </tbody>
      </table>
    </div>
  );
}
