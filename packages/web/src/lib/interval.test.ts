import { describe, expect, it } from "vitest";
import { intervalGeometry } from "./interval";

describe("intervalGeometry", () => {
  it("maps proportions onto the track", () => {
    const g = intervalGeometry(0.0945, 0.9055, 0.5, 100);
    expect(g.bandX).toBeCloseTo(9.45);
    expect(g.bandWidth).toBeCloseTo(81.1);
    expect(g.pointX).toBe(50);
    expect(g.ticks).toEqual([0, 50, 100]);
  });

  it("clamps out-of-range bounds and swaps reversed ones", () => {
    const g = intervalGeometry(1.2, -0.1, 1.5, 80);
    expect(g.bandX).toBe(0);
    expect(g.bandWidth).toBe(80);
    expect(g.pointX).toBe(80);
  });

  it("keeps a degenerate interval visible and inside the track", () => {
    const top = intervalGeometry(1, 1, 1, 100, 4);
    expect(top.bandX).toBe(96);
    expect(top.bandWidth).toBe(4);
    const bottom = intervalGeometry(0, 0, 0, 100, 4);
    expect(bottom.bandX).toBe(0);
    expect(bottom.bandWidth).toBe(4);
    const middle = intervalGeometry(0.5, 0.5, 0.5, 100, 4);
    expect(middle.bandX).toBe(48);
  });

  it("has no point when nothing was scored", () => {
    expect(intervalGeometry(0, 1, null, 100).pointX).toBeNull();
  });
});
