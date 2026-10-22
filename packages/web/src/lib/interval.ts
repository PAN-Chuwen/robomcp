// Geometry of the small interval bar: a [0, 1] track, the Wilson 95% interval as a band, the point estimate
// as a tick. Kept pure so it can be tested without rendering.

export interface IntervalGeometry {
  bandX: number;
  bandWidth: number;
  pointX: number | null; // null when nothing was scored
  ticks: number[]; // x positions of 0, 0.5 and 1
}

const clamp01 = (v: number) => Math.min(Math.max(v, 0), 1);

/**
 * @param lo, hi  interval bounds as proportions (clamped to [0, 1]; swapped if reversed)
 * @param rate    point estimate, or null when nothing was scored
 * @param width   track width in px
 * @param minBand smallest band width drawn, so a degenerate interval stays visible
 */
export function intervalGeometry(
  lo: number,
  hi: number,
  rate: number | null,
  width: number,
  minBand = 2,
): IntervalGeometry {
  let a = clamp01(Math.min(lo, hi)) * width;
  let b = clamp01(Math.max(lo, hi)) * width;
  if (b - a < minBand) {
    const mid = (a + b) / 2;
    a = Math.max(0, Math.min(mid - minBand / 2, width - minBand));
    b = Math.min(width, a + minBand);
  }
  return {
    bandX: a,
    bandWidth: b - a,
    pointX: rate === null ? null : clamp01(rate) * width,
    ticks: [0, width / 2, width],
  };
}
