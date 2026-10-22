import { interval, pct } from "@/lib/format";
import { intervalGeometry } from "@/lib/interval";

/** Wilson 95% interval as a band on a 0–100% track, the success rate as a tick. */
export function IntervalBar({
  lo,
  hi,
  rate,
  width = 96,
  height = 12,
}: {
  lo: number;
  hi: number;
  rate: number | null;
  width?: number;
  height?: number;
}) {
  const g = intervalGeometry(lo, hi, rate, width);
  const mid = height / 2;
  const label = rate === null ? "nothing scored" : `${pct(rate)}, 95% CI ${interval(lo, hi)}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}
      className="inline-block shrink-0 align-middle">
      <title>{label}</title>
      <line x1={0} x2={width} y1={mid} y2={mid} stroke="var(--line)" strokeWidth={2} />
      {g.ticks.map((x, i) => (
        <line key={i} x1={x} x2={x} y1={mid - 3} y2={mid + 3} stroke="var(--line)" strokeWidth={1}
          transform={i === 0 ? "translate(0.5 0)" : i === 2 ? "translate(-0.5 0)" : undefined} />
      ))}
      {rate !== null && (
        <rect x={g.bandX} y={mid - 3} width={g.bandWidth} height={6} rx={2} fill="var(--accent)" opacity={0.35} />
      )}
      {g.pointX !== null && (
        <rect x={Math.min(Math.max(g.pointX - 1, 0), width - 2)} y={1} width={2} height={height - 2} fill="var(--accent)" />
      )}
    </svg>
  );
}

/** "3/4 75% [30%, 95%]" with the bar, for table cells. */
export function Tally({
  successes,
  scored,
  rate,
  wilson,
}: {
  successes: number;
  scored: number;
  rate: number | null;
  wilson: [number, number] | number[];
}) {
  return (
    <span className="inline-flex items-center gap-2 tabular-nums">
      <span className="min-w-[3.5em] text-right">
        {successes}/{scored}
      </span>
      <span className="min-w-[3em] text-right">{pct(rate)}</span>
      <IntervalBar lo={wilson[0]} hi={wilson[1]} rate={rate} />
      <span className="text-muted">{scored ? interval(wilson[0], wilson[1]) : ""}</span>
    </span>
  );
}
