"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Tally } from "@/components/IntervalBar";
import { StatusBadge } from "@/components/StatusBadge";
import { compareHref } from "@/lib/compare";
import { formatDate, pct, shortId } from "@/lib/format";

export interface ExperimentRow {
  id: string;
  name: string | null;
  agent: string;
  suite: string;
  status: string;
  created_at: string;
  repeats: number;
  seeds: number;
  successes: number;
  scored: number;
  episodes: number;
  rate: number | null;
  wilson: number[];
  pass1: number | null;
  passK: number | null; // pass^repeats, when repeats > 1
}

/** Experiments of a project; ticking two opens their paired comparison (older = baseline). */
export function ExperimentTable({ rows }: { rows: ExperimentRow[] }) {
  const router = useRouter();
  const [selected, setSelected] = useState<string[]>([]);

  function toggle(id: string) {
    const next = selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id];
    setSelected(next);
    const href = compareHref(rows.filter((r) => next.includes(r.id)));
    if (href) router.push(href);
  }

  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead>
          <tr>
            <th aria-label="Select for comparison" />
            <th>Experiment</th>
            <th>Agent</th>
            <th>Suite</th>
            <th>Status</th>
            <th>Successes / scored · Wilson 95%</th>
            <th className="num">pass^1</th>
            <th className="num">pass^k</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={selected.includes(r.id) ? "bg-hover" : undefined}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`Compare ${r.name ?? r.id}`}
                  checked={selected.includes(r.id)}
                  disabled={!selected.includes(r.id) && selected.length >= 2}
                  onChange={() => toggle(r.id)}
                  className="accent-[var(--accent)]"
                />
              </td>
              <td>
                <Link href={`/experiments/${r.id}`} className="link">
                  {r.name ?? shortId(r.id)}
                </Link>
              </td>
              <td>{r.agent}</td>
              <td>{r.suite}</td>
              <td>
                <StatusBadge status={r.status} />
              </td>
              <td>
                <Tally successes={r.successes} scored={r.scored} rate={r.rate} wilson={r.wilson} />
                {r.scored < r.episodes && <span className="ml-2 text-muted">of {r.episodes}</span>}
              </td>
              <td className="num">{pct(r.pass1)}</td>
              <td className="num" title={r.repeats > 1 ? `k = ${r.repeats} repeats` : "single repeat"}>
                {r.repeats > 1 ? (
                  <>
                    <span className="text-muted">k={r.repeats} </span>
                    {pct(r.passK)}
                  </>
                ) : (
                  "—"
                )}
              </td>
              <td>{formatDate(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-line px-3 py-2 text-[12.5px] text-muted">
        Tick two experiments to compare them on paired (task, seed, repeat) episodes; the older one is the baseline.
      </p>
    </div>
  );
}
