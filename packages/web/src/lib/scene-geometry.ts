// Top-down view of the tabletop. World frame: robot base at the origin, +x forward, +y left, metres.
// View frame (SVG user units, still metres): u to the right, v down. Forward is drawn up and left is drawn
// left, as if looking down from above and behind the robot: u = -y, v = -x.

import type { Scene } from "./diff";

export const CUBE_SIZE_M = 0.024;

export interface ViewBox {
  minU: number;
  minV: number;
  width: number;
  height: number;
}

export function toView(p: readonly number[]): { u: number; v: number } {
  return { u: -(p[1] ?? 0), v: -(p[0] ?? 0) };
}

/** A box covering the base, every object, the tray and the gripper across all scenes, plus a margin. */
export function sceneViewBox(scenes: Scene[], margin = 0.04): ViewBox {
  const pts: { u: number; v: number }[] = [toView([0, 0])];
  for (const s of scenes) {
    for (const o of s.objects) pts.push(toView(o.position));
    pts.push(toView(s.gripper.position));
    const h = s.tray.size_m / 2;
    const [x, y] = s.tray.position;
    pts.push(toView([x - h, y - h]), toView([x + h, y + h]));
  }
  const us = pts.map((p) => p.u), vs = pts.map((p) => p.v);
  const minU = Math.min(...us) - margin, maxU = Math.max(...us) + margin;
  const minV = Math.min(...vs) - margin, maxV = Math.max(...vs) + margin;
  return { minU, minV, width: maxU - minU, height: maxV - minV };
}

const COLOURS: Record<string, string> = {
  red: "#e5534b",
  green: "#57ab5a",
  blue: "#539bf5",
  yellow: "#d4b13b",
  orange: "#e0823d",
  purple: "#a371f7",
  white: "#d0d7de",
  black: "#545d68",
};

/** Colour from the first word of an object name (`red_cube` → red); grey when unknown. */
export function objectColour(name: string): string {
  return COLOURS[name.split(/[_\s-]/)[0]?.toLowerCase() ?? ""] ?? "#8b949e";
}

/** Grid line positions (metres) every `step` within [lo, hi]. */
export function gridLines(lo: number, hi: number, step = 0.05): number[] {
  const out: number[] = [];
  for (let k = Math.ceil(lo / step); k * step <= hi + 1e-9; k++) out.push(Number((k * step).toFixed(6)));
  return out;
}
