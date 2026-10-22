// Comparison helpers: which selected experiment is the baseline, and how to state the verdict.

import { formatP } from "./format";

/** The older experiment is the baseline, the newer the candidate. */
export function compareHref(selected: { id: string; created_at: string }[]): string | null {
  if (selected.length !== 2) return null;
  const [a, b] = [...selected].sort((x, y) => Date.parse(x.created_at) - Date.parse(y.created_at));
  return `/compare?baseline=${encodeURIComponent(a.id)}&candidate=${encodeURIComponent(b.id)}`;
}

export type Verdict = "regression" | "improvement" | "no_significant_difference";

export interface VerdictInput {
  verdict: Verdict;
  p_value: number;
  only_baseline: number;
  only_candidate: number;
  pairs: number;
}

export function verdictText(c: VerdictInput): { title: string; detail: string; tone: "bad" | "good" | "muted" } {
  const discordant = c.only_baseline + c.only_candidate;
  const p = `exact McNemar p = ${formatP(c.p_value)}`;
  const counts = `${c.only_candidate} pair${c.only_candidate === 1 ? "" : "s"} only the candidate solved, ` +
    `${c.only_baseline} only the baseline solved (${discordant} discordant of ${c.pairs})`;
  switch (c.verdict) {
    case "regression":
      return { title: "Regression", detail: `${counts}; ${p}`, tone: "bad" };
    case "improvement":
      return { title: "Improvement", detail: `${counts}; ${p}`, tone: "good" };
    default:
      return { title: "No significant difference", detail: `${counts}; ${p}`, tone: "muted" };
  }
}
