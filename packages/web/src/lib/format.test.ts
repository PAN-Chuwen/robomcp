import { describe, expect, it } from "vitest";
import { formatP, pct } from "./format";

describe("formatP", () => {
  it("shows four significant digits and never rounds a small p to zero", () => {
    expect(formatP(1)).toBe("1");
    expect(formatP(0.0312500001)).toBe("0.03125");
    expect(formatP(0.5)).toBe("0.5");
    expect(formatP(0.00001907)).toBe("1.91e-5");
    expect(formatP(Number.NaN)).toBe("—");
  });
});

describe("pct", () => {
  it("formats proportions and missing values", () => {
    expect(pct(0.5)).toBe("50%");
    expect(pct(0.3424, 1)).toBe("34.2%");
    expect(pct(null)).toBe("—");
  });
});
