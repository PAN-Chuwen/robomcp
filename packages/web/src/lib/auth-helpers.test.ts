import { describe, expect, it } from "vitest";
import { isSameOrigin, safeNext } from "./auth-helpers";

describe("safeNext", () => {
  it("keeps same-site paths", () => {
    expect(safeNext("/projects/abc?x=1")).toBe("/projects/abc?x=1");
  });

  it("rejects open redirects and loops back to sign-in", () => {
    for (const bad of [null, "", "https://evil.example", "//evil.example", "/\\evil.example", "projects",
      "/sign-in?next=/", "/auth/sign-out"]) {
      expect(safeNext(bad)).toBe("/");
    }
  });
});

describe("isSameOrigin", () => {
  it("accepts a matching origin and a missing one", () => {
    expect(isSameOrigin("http://localhost:3000", "localhost:3000")).toBe(true);
    expect(isSameOrigin(null, "localhost:3000")).toBe(true);
  });

  it("rejects a foreign or malformed origin", () => {
    expect(isSameOrigin("https://evil.example", "localhost:3000")).toBe(false);
    expect(isSameOrigin("null", "localhost:3000")).toBe(false);
    expect(isSameOrigin("http://localhost:3000", null)).toBe(false);
  });
});
