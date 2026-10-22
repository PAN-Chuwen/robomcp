// Display formatting shared by server and client components.

export function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

/** An exact p-value: four significant digits, scientific below 0.0001, never rounded to 0. */
export function formatP(p: number): string {
  if (!Number.isFinite(p)) return "—";
  if (p >= 1) return "1";
  if (p === 0) return "0";
  if (p < 1e-4) return p.toExponential(2);
  return String(Number(p.toPrecision(4)));
}

export function interval(lo: number, hi: number): string {
  return `[${pct(lo)}, ${pct(hi)}]`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function formatMetric(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-US") : String(Number(v.toFixed(2)));
  return String(v);
}

export function formatVec(v: readonly number[] | undefined, digits = 3): string {
  return v ? v.map((x) => x.toFixed(digits)).join(", ") : "—";
}
