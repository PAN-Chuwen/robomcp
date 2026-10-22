import { describe, expect, it } from "vitest";
import { diffObservation, observedScene, type Scene } from "./diff";

function scene(over: Partial<{ red: [number, number, number]; inTray: boolean; holding: boolean | string | null }> = {}): Scene {
  return {
    objects: [
      { name: "red_cube", position: over.red ?? [0.1661, 0.0664, 0.012], in_tray: over.inTray ?? false, lifted: false },
      { name: "blue_cube", position: [0.2095, -0.0211, 0.012], in_tray: false, lifted: false },
    ],
    tray: { position: [0.12, 0.2, 0], size_m: 0.08 },
    gripper: { position: [0.177, -0.001, 0.058], opening: 1.2, holding: over.holding ?? null },
  };
}

describe("observedScene", () => {
  it("finds the scene in a skill result and in a get_scene result", () => {
    const s = scene();
    expect(observedScene({ ok: true, message: "done", scene: s })).toBe(s);
    expect(observedScene(s)).toBe(s);
    expect(observedScene("<Image>")).toBeNull();
    expect(observedScene({ ok: true, message: "saved" })).toBeNull();
  });
});

describe("diffObservation", () => {
  it("is empty when the agent saw the truth (bool holding vs held name is not a difference)", () => {
    const d = diffObservation({ ok: true, message: "done", scene: scene({ holding: true }) },
      scene({ holding: "red_cube" }));
    expect(d.flagged).toBe(0);
    expect(d.holding).toEqual({ observed: true, truth: "red_cube", differs: false });
    expect(d.objects.every((o) => o.deltaMm === 0)).toBe(true);
  });

  it("flags a position error above 1 mm but not below", () => {
    const far = diffObservation(scene({ red: [0.1681, 0.0664, 0.012] }), scene());
    expect(far.objects[0]).toMatchObject({ name: "red_cube", positionDiffers: true, flagged: true });
    expect(far.objects[0].deltaMm).toBeCloseTo(2, 6);
    expect(far.flagged).toBe(1);
    const near = diffObservation(scene({ red: [0.1666, 0.0664, 0.012] }), scene());
    expect(near.objects[0].flagged).toBe(false);
    expect(near.objects[0].deltaMm).toBeCloseTo(0.5, 6);
  });

  it("flags a stale in_tray", () => {
    const d = diffObservation({ ok: true, message: "done", scene: scene({ inTray: true }) }, scene({ inTray: false }));
    expect(d.objects[0]).toMatchObject({ inTrayDiffers: true, positionDiffers: false, flagged: true });
  });

  it("flags a holding disagreement", () => {
    const d = diffObservation(scene({ holding: false }), scene({ holding: "red_cube" }));
    expect(d.holding.differs).toBe(true);
    expect(d.flagged).toBe(1);
  });

  it("reports blocked actions and the skill message", () => {
    const d = diffObservation({ ok: false, message: "blocked by safety gate: below table", blocked: true,
      scene: scene() }, scene());
    expect(d).toMatchObject({ blocked: true, ok: false, message: "blocked by safety gate: below table", flagged: 0 });
  });

  it("flags objects the agent did not see and objects that do not exist", () => {
    const obs = scene();
    obs.objects = [obs.objects[0], { name: "ghost_cube", position: [0, 0, 0], in_tray: false }];
    const d = diffObservation(obs, scene());
    expect(d.objects.map((o) => [o.name, o.observed !== null, o.truth !== null, o.flagged])).toEqual([
      ["red_cube", true, true, false],
      ["blue_cube", false, true, true],
      ["ghost_cube", true, false, true],
    ]);
    expect(d.flagged).toBe(2);
  });

  it("compares nothing when the tool returned no scene", () => {
    const d = diffObservation("<Image>", scene());
    expect(d.hasScene).toBe(false);
    expect(d.flagged).toBe(0);
    expect(d.objects).toHaveLength(2);
  });
});
