import type { Scene, StepDiff } from "@/lib/diff";
import { CUBE_SIZE_M, gridLines, objectColour, toView, type ViewBox } from "@/lib/scene-geometry";

const FONT = 0.0085; // 8.5 mm in scene units

/**
 * Top-down view of the true scene at one step: robot base at the origin, forward (+x) up, left (+y) left.
 * Where the agent's observation of an object is off by more than the tolerance, a dashed outline marks
 * where the agent believed it was.
 */
export function SceneView({ truth, diff, box }: { truth: Scene; diff: StepDiff; box: ViewBox }) {
  const half = CUBE_SIZE_M / 2;
  const tray = toView(truth.tray.position);
  const traySize = truth.tray.size_m;
  const grip = toView(truth.gripper.position);
  const holding = truth.gripper.holding;
  const us = gridLines(box.minU, box.minU + box.width);
  const vs = gridLines(box.minV, box.minV + box.height);
  const stroke = { vectorEffect: "non-scaling-stroke" as const };

  return (
    <svg
      viewBox={`${box.minU} ${box.minV} ${box.width} ${box.height}`}
      className="block h-auto max-h-[62vh] w-full bg-bg"
      role="img"
      aria-label="Top-down view of the true scene"
    >
      {/* 5 cm grid; labels give world coordinates (x forward, y left) */}
      {us.map((u) => (
        <line key={`u${u}`} x1={u} x2={u} y1={box.minV} y2={box.minV + box.height} stroke="var(--line)"
          strokeWidth={u === 0 ? 1.5 : 0.75} {...stroke} />
      ))}
      {vs.map((v) => (
        <line key={`v${v}`} x1={box.minU} x2={box.minU + box.width} y1={v} y2={v} stroke="var(--line)"
          strokeWidth={v === 0 ? 1.5 : 0.75} {...stroke} />
      ))}
      {vs.filter((v) => v < 0).map((v) => (
        <text key={`vl${v}`} x={box.minU + 0.004} y={v - 0.003} fontSize={FONT} fill="var(--muted)" fontFamily="var(--mono)">
          x {(-v).toFixed(2)}
        </text>
      ))}
      {us.filter((u) => u !== 0).map((u) => (
        <text key={`ul${u}`} x={u + 0.003} y={box.minV + box.height - 0.004} fontSize={FONT} fill="var(--muted)"
          fontFamily="var(--mono)">
          y {(-u).toFixed(2)}
        </text>
      ))}

      {/* robot base */}
      <circle cx={0} cy={0} r={0.028} fill="var(--panel)" stroke="var(--muted)" strokeWidth={1.25} {...stroke} />
      <path d="M 0 -0.028 L 0 -0.045" stroke="var(--muted)" strokeWidth={1.25} {...stroke} />
      <text x={0} y={0.006} fontSize={FONT} fill="var(--muted)" textAnchor="middle" fontFamily="var(--mono)">
        base
      </text>

      {/* tray */}
      <rect x={tray.u - traySize / 2} y={tray.v - traySize / 2} width={traySize} height={traySize}
        fill="var(--accent)" fillOpacity={0.08} stroke="var(--accent)" strokeWidth={1.25} {...stroke} />
      <text x={tray.u - traySize / 2 + 0.003} y={tray.v - traySize / 2 + FONT + 0.001} fontSize={FONT}
        fill="var(--accent)" fontFamily="var(--mono)">
        tray
      </text>

      {/* where the agent believed objects were, when that differs from the truth */}
      {diff.objects
        .filter((o) => o.positionDiffers && o.observed)
        .map((o) => {
          const seen = toView(o.observed!.position);
          const real = toView(o.truth!.position);
          return (
            <g key={`obs-${o.name}`}>
              <line x1={seen.u} y1={seen.v} x2={real.u} y2={real.v} stroke="var(--bad)" strokeWidth={1}
                strokeDasharray="3 2" {...stroke} />
              <rect x={seen.u - half} y={seen.v - half} width={CUBE_SIZE_M} height={CUBE_SIZE_M} fill="none"
                stroke="var(--bad)" strokeWidth={1.25} strokeDasharray="3 2" {...stroke} />
            </g>
          );
        })}

      {/* true object positions */}
      {truth.objects.map((o) => {
        const p = toView(o.position);
        const flagged = diff.objects.find((d) => d.name === o.name)?.flagged;
        return (
          <g key={o.name}>
            <rect x={p.u - half} y={p.v - half} width={CUBE_SIZE_M} height={CUBE_SIZE_M} rx={0.002}
              fill={objectColour(o.name)} fillOpacity={o.lifted ? 0.55 : 0.95}
              stroke={flagged ? "var(--bad)" : o.lifted ? "var(--fg)" : "none"} strokeWidth={flagged ? 2 : 1}
              strokeDasharray={o.lifted && !flagged ? "2 2" : undefined} {...stroke}>
              <title>
                {`${o.name} (${o.position.map((v) => v.toFixed(3)).join(", ")})${o.in_tray ? " in tray" : ""}${o.lifted ? " lifted" : ""}`}
              </title>
            </rect>
            <text x={p.u} y={p.v + half + FONT + 0.001} fontSize={FONT} textAnchor="middle" fill="var(--fg)"
              fontFamily="var(--mono)">
              {o.name.replace(/_cube$/, "")}
              {o.lifted ? ` z${(o.position[2] * 100).toFixed(1)}` : ""}
            </text>
          </g>
        );
      })}

      {/* gripper */}
      <g>
        <circle cx={grip.u} cy={grip.v} r={0.009} fill={holding ? "var(--tool)" : "none"} fillOpacity={0.35}
          stroke="var(--tool)" strokeWidth={1.5} {...stroke} />
        <path d={`M ${grip.u - 0.015} ${grip.v} H ${grip.u + 0.015} M ${grip.u} ${grip.v - 0.015} V ${grip.v + 0.015}`}
          stroke="var(--tool)" strokeWidth={1} {...stroke} />
        <title>{`gripper (${truth.gripper.position.map((v) => v.toFixed(3)).join(", ")}) opening ${truth.gripper.opening}${holding ? ` holding ${holding}` : ""}`}</title>
      </g>
    </svg>
  );
}
