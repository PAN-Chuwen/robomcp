"""Command line entry for the RoboMCP agent harness.

  robomcp-agent run "把红色方块放进托盘" --mode plan --seed 3 [--record demo.gif]
  robomcp-agent eval --modes bare,verify,plan --seeds 0,1,2
  robomcp-agent console [--port 8765]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from robomcp.agent.harness import PROJECT_ROOT, Harness
from robomcp.agent.tasks import TASKS


async def _eval(modes: list[str], seeds: list[int], keys: list[str] | None) -> list[dict]:
    rows = []
    tasks = [t for t in TASKS if not keys or t.key in keys]
    for mode in modes:
        harness = Harness(mode=mode, verbose=False)
        for task in tasks:
            for seed in seeds:
                res = await harness.run(task.goal, seed=seed)
                ok = task.check(res.scene_before, res.scene_after)
                u = harness.llm.usage
                rows.append({"mode": mode, "task": task.key, "kind": task.kind, "seed": seed, "success": ok,
                             "tool_calls": res.tool_calls, "model_calls": u.calls, "prompt_tokens": u.prompt,
                             "cache_hit": u.cache_hit, "seconds": res.seconds, "trace": res.trace_path})
                print(f"{mode:<7}{task.key:<16}seed={seed}  {'✓' if ok else '✗'}  tools={res.tool_calls:<3}"
                      f"calls={u.calls:<3}{res.seconds:>6.1f}s", flush=True)
    return rows


def _summary(rows: list[dict]) -> None:
    print(f"\n{'mode':<8}{'success':>10}{'tool calls':>12}{'model calls':>13}{'tokens':>10}{'cache hit':>11}{'sec':>7}")
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
    e = sub.add_parser("eval", help="run the task set under several harness modes")
    e.add_argument("--modes", default="bare,verify,plan")
    e.add_argument("--seeds", default="0,1,2")
    e.add_argument("--tasks", help="comma-separated task keys (default: all)")
    c = sub.add_parser("console", help="web console with live view")
    c.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    if args.cmd == "run":
        res = asyncio.run(Harness(mode=args.mode).run(args.goal, seed=args.seed, record=args.record))
        print(f"\n结果：{res.final_text}\n轨迹：{res.trace_path}")
    elif args.cmd == "eval":
        rows = asyncio.run(_eval(args.modes.split(","), [int(s) for s in args.seeds.split(",")],
                                 args.tasks.split(",") if args.tasks else None))
        _summary(rows)
        out = PROJECT_ROOT / "out" / f"eval-{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"\nresults: {out}")
    else:
        from robomcp.agent.console import serve
        serve(args.port)


if __name__ == "__main__":
    main()
