// What the agent saw vs the ground truth, for one episode-log step.
//
// Perception is an oracle today, so observed positions equal the truth; the diff exists for noisy perception
// (M4) and for stale tool results. `holding` differs in type by design: observations carry a bool, the truth
// carries the held object's name (or null), so only a disagreement in *whether* something is held counts.

export type Vec3 = [number, number, number];

export interface SceneObject {
  name: string;
  position: Vec3;
  in_tray: boolean;
  lifted?: boolean;
  distance_to_tray_m?: number;
}

export interface Scene {
  objects: SceneObject[];
  tray: { position: Vec3; size_m: number };
  gripper: { position: Vec3; opening: number; holding: boolean | string | null };
}

/** Positions are logged to 0.1 mm; anything beyond 1 mm is a real disagreement. */
export const POSITION_TOL_M = 1e-3;

export interface ObjectDiff {
  name: string;
  observed: SceneObject | null; // null: the agent's observation does not include this object
  truth: SceneObject | null; // null: the agent reported an object that does not exist
  deltaMm: number | null;
  positionDiffers: boolean;
  inTrayDiffers: boolean;
  flagged: boolean;
}

export interface StepDiff {
  hasScene: boolean; // false when the tool returned no scene (e.g. recording tools), so nothing to compare
  ok: boolean | null;
  message: string | null;
  blocked: boolean;
  objects: ObjectDiff[];
  holding: { observed: boolean | null; truth: string | null; differs: boolean };
  flagged: number; // objects flagged + holding mismatch
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** The scene inside an observation: skills return {ok, message, scene}, get_scene returns the scene itself. */
export function observedScene(observation: unknown): Scene | null {
  if (!isObj(observation)) return null;
  const s = "scene" in observation ? observation.scene : observation;
  return isObj(s) && Array.isArray(s.objects) && isObj(s.gripper) ? (s as unknown as Scene) : null;
}

export function distanceM(a: readonly number[], b: readonly number[]): number {
  return Math.hypot(...a.map((v, i) => v - (b[i] ?? 0)));
}

function heldName(h: boolean | string | null | undefined): string | null {
  if (typeof h === "string") return h;
  return h ? "(something)" : null;
}

export function diffObservation(observation: unknown, truth: Scene): StepDiff {
  const obs = observedScene(observation);
  const meta = isObj(observation) ? observation : {};
  const ok = typeof meta.ok === "boolean" ? meta.ok : null;
  const message = typeof meta.message === "string" ? meta.message : null;
  const blocked = meta.blocked === true;
  const trueHeld = heldName(truth.gripper.holding);

  if (!obs) {
    return {
      hasScene: false,
      ok,
      message,
      blocked,
      objects: truth.objects.map((t) => ({
        name: t.name, observed: null, truth: t, deltaMm: null, positionDiffers: false, inTrayDiffers: false,
        flagged: false,
      })),
      holding: { observed: null, truth: trueHeld, differs: false },
      flagged: 0,
    };
  }

  const seen = new Map(obs.objects.map((o) => [o.name, o]));
  const objects: ObjectDiff[] = truth.objects.map((t) => {
    const o = seen.get(t.name) ?? null;
    seen.delete(t.name);
    if (!o) {
      return { name: t.name, observed: null, truth: t, deltaMm: null, positionDiffers: false, inTrayDiffers: false,
        flagged: true };
    }
    const d = distanceM(o.position, t.position);
    const positionDiffers = d > POSITION_TOL_M;
    const inTrayDiffers = o.in_tray !== t.in_tray;
    return { name: t.name, observed: o, truth: t, deltaMm: d * 1000, positionDiffers, inTrayDiffers,
      flagged: positionDiffers || inTrayDiffers };
  });
  for (const o of seen.values()) {
    objects.push({ name: o.name, observed: o, truth: null, deltaMm: null, positionDiffers: false,
      inTrayDiffers: false, flagged: true });
  }

  const h = obs.gripper.holding;
  const observedHolding = typeof h === "boolean" ? h : typeof h === "string" ? true : h === null ? false : null;
  const holdingDiffers = observedHolding !== null && observedHolding !== (trueHeld !== null);
  return {
    hasScene: true,
    ok,
    message,
    blocked,
    objects,
    holding: { observed: observedHolding, truth: trueHeld, differs: holdingDiffers },
    flagged: objects.filter((o) => o.flagged).length + (holdingDiffers ? 1 : 0),
  };
}
