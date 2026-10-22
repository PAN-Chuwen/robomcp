import { describe, expect, it } from "vitest";
import { compareHref, verdictText } from "./compare";

describe("compareHref", () => {
  it("makes the older experiment the baseline regardless of selection order", () => {
    const older = { id: "a", created_at: "2026-10-22T09:00:44Z" };
    const newer = { id: "b", created_at: "2026-10-22T09:01:00Z" };
    expect(compareHref([newer, older])).toBe("/compare?baseline=a&candidate=b");
    expect(compareHref([older, newer])).toBe("/compare?baseline=a&candidate=b");
  });

  it("needs exactly two", () => {
    expect(compareHref([])).toBeNull();
    expect(compareHref([{ id: "a", created_at: "2026-10-22T09:00:44Z" }])).toBeNull();
  });
});

describe("verdictText", () => {
  it("states the discordant counts and the exact p-value", () => {
    const v = verdictText({ verdict: "regression", p_value: 0.0390625, only_baseline: 7, only_candidate: 1, pairs: 20 });
    expect(v.tone).toBe("bad");
    expect(v.title).toBe("Regression");
    expect(v.detail).toBe("1 pair only the candidate solved, 7 only the baseline solved (8 discordant of 20); " +
      "exact McNemar p = 0.03906");
  });

  it("reports no significant difference neutrally", () => {
    const v = verdictText({ verdict: "no_significant_difference", p_value: 1, only_baseline: 0, only_candidate: 1,
      pairs: 2 });
    expect(v).toMatchObject({ title: "No significant difference", tone: "muted" });
    expect(v.detail).toContain("p = 1");
  });
});
