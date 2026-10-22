import { describe, expect, it } from "vitest";
import type { Scene } from "./diff";
import { gridLines, objectColour, sceneViewBox, toView } from "./scene-geometry";

describe("toView", () => {
  it("draws forward (+x) up and left (+y) to the left", () => {
    expect(toView([0.2, 0, 0])).toEqual({ u: -0, v: -0.2 });
    expect(toView([0, 0.1, 0])).toEqual({ u: -0.1, v: -0 });
    expect(toView([0, -0.1, 0]).u).toBeGreaterThan(0); // right of the base
  });
});

describe("sceneViewBox", () => {
  const s: Scene = {
    objects: [{ name: "red_cube", position: [0.3, -0.1, 0.012], in_tray: false }],
    tray: { position: [0.12, 0.2, 0], size_m: 0.08 },
    gripper: { position: [0.17, 0, 0.06], opening: 1, holding: false },
  };

  it("covers the base, objects and tray corners with a margin", () => {
    const b = sceneViewBox([s], 0.01);
    expect(b.minU).toBeCloseTo(-0.25); // tray left edge y = 0.24 -> u = -0.24, minus margin
    expect(b.minU + b.width).toBeCloseTo(0.11); // cube at y = -0.1
    expect(b.minV).toBeCloseTo(-0.31); // cube at x = 0.3
    expect(b.minV + b.height).toBeCloseTo(0.01); // robot base
  });
});

describe("objectColour", () => {
  it("colours by the first word of the name", () => {
    expect(objectColour("red_cube")).toBe("#e5534b");
    expect(objectColour("Blue cube")).toBe("#539bf5");
    expect(objectColour("mystery")).toBe("#8b949e");
  });
});

describe("gridLines", () => {
  it("lists multiples of the step inside the range", () => {
    expect(gridLines(-0.12, 0.11)).toEqual([-0.1, -0.05, 0, 0.05, 0.1]);
  });
});
