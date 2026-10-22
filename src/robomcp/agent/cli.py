"""Command line entry for the RoboMCP agent harness.

  robomcp-agent run "把红色方块放进托盘" --mode plan --seed 3 [--record demo.gif]
  robomcp-agent eval --modes bare,verify,plan --seeds 0,1,2
  robomcp-agent replay out/traces/<run>.jsonl [--no-render]
  robomcp-agent console [--port 8765]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from robomcp.agent.harness import PROJECT_ROOT, Harness
from robomcp.agent.tasks import TASKS


async def _eval(modes: list[str], seeds: list[int], keys: list[str] | None, slip: float, slip_mode: str,
                out) -> list[dict]:
    rows = []
    tasks = [t for t in TASKS if not keys or t.key in keys]
    for mode in modes:
        harness = Harness(mode=mode, verbose=False, slip=slip, slip_mode=slip_mode)
        for task in tasks:
            for seed in seeds:
                row = {"mode": mode, "task": task.key, "kind": task.kind, "seed": seed, "slip": slip,
                       "slip_mode": slip_mode}
                try:
                    res = await harness.run(task.goal, seed=seed)
                    u = harness.llm.usage
                    row.update(success=task.check(res.scene_before, res.scene_after), error=None,
                               tool_calls=res.tool_calls, model_calls=u.calls, prompt_tokens=u.prompt,
                               cache_hit=u.cache_hit, seconds=res.seconds, trace=res.trace_path)
                except Exception as e:  # network hiccups etc.: record and keep going
                    row.update(success=False, error=f"{type(e).__name__}: {e}"[:200], tool_calls=0, model_calls=0,
                               prompt_tokens=0, cache_hit=0, seconds=0.0, trace="")
                rows.append(row)
                out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))  # save as we go
                mark = "!" if row["error"] else ("✓" if row["success"] else "✗")
                print(f"{mode:<7}{task.key:<16}seed={seed}  {mark}  tools={row['tool_calls']:<3}"
                      f"calls={row['model_calls']:<3}{row['seconds']:>6.1f}s", flush=True)
    return rows


def _summary(rows: list[dict]) -> None:
    print(f"\n{'mode':<8}{'success':>10}{'tool calls':>12}{'model calls':>13}{'tokens':>10}{'cache hit':>11}{'sec':>7}")
    errors = [r for r in rows if r.get("error")]
    if errors:
        print(f"\n{len(errors)} runs failed with errors and are excluded from the averages below")
    rows = [r for r in rows if not r.get("error")]
    for mode in dict.fromkeys(r["mode"] for r in rows):
        rs = [r for r in rows if r["mode"] == mode]
        n = len(rs)
        tok = sum(r["prompt_tokens"] for r in rs)
        print(f"{mode:<8}{sum(r['success'] for r in rs):>6}/{n:<3}{sum(r['tool_calls'] for r in rs) / n:>12.1f}"
              f"{sum(r['model_calls'] for r in rs) / n:>13.1f}{tok / n:>10.0f}"
              f"{(sum(r['cache_hit'] for r in rs) / tok if tok else 0):>10.1%}{sum(r['seconds'] for r in rs) / n:>7.1f}")
    kinds = dict.fromkeys(r["kind"] for r in rows)
    print("\nsuccess by task type: " + "  ".join(
        f"{k}: " + "/".join(f"{m}={sum(r['success'] for r in rows if r['kind'] == k and r['mode'] == m)}"
                            for m in dict.fromkeys(r['mode'] for r in rows)) for k in kinds))


def main() -> None:
    ap = argparse.ArgumentParser(prog="robomcp-agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run one task")
    r.add_argument("goal")
    r.add_argument("--mode", default="plan", choices=["bare", "verify", "plan"])
    r.add_argument("--seed", type=int)
    r.add_argument("--record", help="save a GIF under out/")
    r.add_argument("--slip", type=float, default=0.0, help="probability of a silent placement failure")
    r.add_argument("--slip-mode", default="immediate", choices=["immediate", "delayed"])
    e = sub.add_parser("eval", help="run the task set under several harness modes")
    e.add_argument("--modes", default="bare,verify,plan")
    e.add_argument("--seeds", default="0,1,2")
    e.add_argument("--tasks", help="comma-separated task keys (default: all)")
    e.add_argument("--slip", type=float, default=0.0, help="probability of a silent placement failure")
    e.add_argument("--slip-mode", default="immediate", choices=["immediate", "delayed"],
                   help="delayed: the object rolls off after the tool has returned, so its result is stale")
    p = sub.add_parser("replay", help="replay a trace in the simulator, check it step by step, write a viewer")
    p.add_argument("trace")
    p.add_argument("--no-render", action="store_true", help="only check reproducibility, no frames or page")
    c = sub.add_parser("console", help="web console with live view")
    c.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    if args.cmd == "run":
        res = asyncio.run(Harness(mode=args.mode, slip=args.slip, slip_mode=args.slip_mode).run(args.goal, seed=args.seed, record=args.record))
        print(f"\n结果：{res.final_text}\n轨迹：{res.trace_path}")
    elif args.cmd == "eval":
        out = PROJECT_ROOT / "out" / f"eval-{time.strftime('%Y%m%d-%H%M%S')}-slip{args.slip}-{args.slip_mode}.json"
        out.parent.mkdir(exist_ok=True)
        rows = asyncio.run(_eval(args.modes.split(","), [int(s) for s in args.seeds.split(",")],
                                 args.tasks.split(",") if args.tasks else None, args.slip, args.slip_mode, out))
        _summary(rows)
        print(f"\nresults: {out}")
    elif args.cmd == "replay":
        from pathlib import Path

        from robomcp.agent.replay import replay, report, write_viewer

        rep = asyncio.run(replay(Path(args.trace), render=not args.no_render))
        report(rep)
        if not args.no_render:
            print(f"viewer: {write_viewer(rep)}")
        raise SystemExit(0 if rep.divergence is None else 1)
    else:
        from robomcp.agent.console import serve
        serve(args.port)


if __name__ == "__main__":
    main()
