"""A small agent harness that drives the RoboMCP tools with an LLM.

Three modes, so the same model can be compared under different harness designs:
  bare    plain agent loop: model calls tools until it stops
  verify  + a verifier sub-agent (fresh context) that checks the final scene; failures go back to the executor
  plan    + a planner sub-agent that checks feasibility and writes the steps first, then executor + verifier
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from robomcp.agent.llm import LLM, PROJECT_ROOT, Usage, mcp_to_openai_tools

TRACE_DIR = PROJECT_ROOT / "out" / "traces"
HIDDEN_TOOLS = {"look", "start_recording", "save_recording", "reset_scene"}  # harness-only or not text-model friendly

EXECUTOR_PROMPT = """你控制一台桌面机械臂（MuJoCo 仿真）。坐标单位是米：+x 向前，+y 向左，z 向上，桌面 z=0。
规则：
1. 先调用 get_scene 看清场景，只操作场景里真实存在的物体。
2. 优先用 pick + place_in_tray / place_at 这些技能，move_to 只在必要时用。
3. 每个技能都会返回 ok、message 和最新场景；ok=false 时根据 message 调整，不要假装成功。
4. 任务做不到（比如物体不存在、够不到）就停止并说明原因。
5. 完成后用一两句话说明结果，不要再调用工具。"""

PLANNER_PROMPT = """你是机械臂任务的规划者。根据任务和当前场景，判断任务能否完成，并写出步骤。
只输出 JSON：{"feasible": true/false, "reason": "一句话", "steps": ["步骤1", "步骤2", ...]}
步骤用可执行的技能描述，比如 "pick red_cube"、"place_in_tray"。物体不存在时 feasible=false。"""

VERIFIER_PROMPT = """你是校验者。对比执行前和执行后的场景，判断任务是否真正完成。
任务里提到的"最远"、"不要动"等都以执行前的场景为准。
如果任务要求的物体在执行前的场景里根本不存在，执行者拒绝执行且没有移动任何物体，就算通过。
只看场景数据，不要相信执行者自己的说法。只输出 JSON：{"passed": true/false, "reason": "一句话"}"""


LIVE_DIR = PROJECT_ROOT / "out" / "live"


def _server_params(live: bool, slip: float = 0.0, slip_mode: str = "immediate") -> StdioServerParameters:
    env = dict(os.environ)
    if live:
        env["ROBOMCP_LIVE_DIR"] = str(LIVE_DIR)
    env["ROBOMCP_SLIP"] = str(slip)
    env["ROBOMCP_SLIP_MODE"] = slip_mode
    return StdioServerParameters(command=sys.executable, args=["-m", "robomcp.server"], env=env)


def _text(result) -> str:
    parts = [c.text for c in result.content if hasattr(c, "text")]
    return "\n".join(parts) if parts else str(result)


def _json(text: str) -> dict:
    """Parse the first JSON object in a model reply (models sometimes wrap it in ``` fences)."""
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1]) if start >= 0 < end else {}


@dataclass
class RunResult:
    goal: str
    mode: str
    final_text: str = ""
    tool_calls: int = 0
    verifier_rounds: int = 0
    planner: dict | None = None
    seconds: float = 0.0
    trace_path: str = ""
    scene_before: dict = field(default_factory=dict)
    scene_after: dict = field(default_factory=dict)
    events: list = field(default_factory=list)


class Harness:
    def __init__(self, mode: str = "plan", max_turns: int = 20, max_verify: int = 2, verbose: bool = True,
                 on_event=None, live: bool = False, slip: float = 0.0, slip_mode: str = "immediate"):
        assert mode in ("bare", "verify", "plan"), mode
        self.mode, self.max_turns, self.max_verify, self.verbose = mode, max_turns, max_verify, verbose
        self.on_event, self.live = on_event, live  # on_event(dict) feeds the web console
        self.slip = slip  # probability of a silent placement failure injected by the simulator
        self.slip_mode = slip_mode  # "immediate" (visible in the tool result) or "delayed" (tool result is stale)
        self.llm = LLM()

    # ------------------------------------------------------------------ utils

    def _log(self, res: RunResult, kind: str, **data) -> None:
        event = {"t": round(time.time(), 3), "kind": kind, **data}
        res.events.append(event)
        if self.on_event:
            self.on_event(event)
        if self.verbose:
            line = {
                "plan": lambda: f"[规划] feasible={data['plan'].get('feasible')} 步骤={data['plan'].get('steps')} 理由={data['plan'].get('reason')}",
                "tool": lambda: f"[执行] {data['name']}({json.dumps(data['args'], ensure_ascii=False)}) -> {data['summary']}",
                "say": lambda: f"[执行] 说：{data['text']}",
                "verify": lambda: f"[校验] passed={data['verdict'].get('passed')} 理由={data['verdict'].get('reason')}",
            }.get(kind, lambda: f"[{kind}] {data}")()
            print(line, flush=True)

    @staticmethod
    def _summary(text: str) -> str:
        try:
            d = json.loads(text)
        except json.JSONDecodeError:
            return text[:80]
        if "ok" in d:
            return f"ok={d['ok']} {d.get('message', '')}"
        return "场景已读取"

    # --------------------------------------------------------------- sub-agents

    def _plan(self, goal: str, scene: str) -> dict:
        msg = self.llm.chat([
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": f"任务：{goal}\n当前场景：{scene}"},
        ])
        return _json(msg.content or "") or {"feasible": True, "reason": "planner output unparsable", "steps": []}

    def _verify(self, goal: str, before: str, after: str, claim: str) -> dict:
        msg = self.llm.chat([
            {"role": "system", "content": VERIFIER_PROMPT},
            {"role": "user", "content": f"任务：{goal}\n执行者的说法：{claim}\n执行前的场景：{before}\n执行后的场景：{after}"},
        ])
        return _json(msg.content or "") or {"passed": False, "reason": "verifier output unparsable"}

    # ----------------------------------------------------------------- the loop

    async def _executor(self, robot: Client, tools: list[dict], messages: list[dict], res: RunResult) -> str:
        for _ in range(self.max_turns):
            msg = self.llm.chat(messages, tools)
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                self._log(res, "say", text=msg.content)
                return msg.content or ""
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                out = _text(await robot.call_tool(call.function.name, args))
                res.tool_calls += 1
                self._log(res, "tool", name=call.function.name, args=args, summary=self._summary(out))
                messages.append({"role": "tool", "tool_call_id": call.id, "content": out})
        return "（达到最大轮数，停止）"

    async def run(self, goal: str, seed: int | None = None, record: str | None = None) -> RunResult:
        res = RunResult(goal=goal, mode=self.mode)
        self.llm.usage = Usage()
        t0 = time.time()
        self._log(res, "start", goal=goal, mode=self.mode, seed=seed, slip=self.slip,
                  slip_mode=self.slip_mode)
        async with Client(_server_params(self.live, self.slip, self.slip_mode)) as robot:
            tools = mcp_to_openai_tools((await robot.list_tools()).tools, HIDDEN_TOOLS)
            await robot.call_tool("reset_scene", {"seed": seed} if seed is not None else {})
            if record:
                await robot.call_tool("start_recording", {})
            scene = _text(await robot.call_tool("get_scene", {}))
            res.scene_before = json.loads(scene)

            await self._solve(robot, tools, goal, scene, res)

            res.scene_after = json.loads(_text(await robot.call_tool("get_scene", {})))
            if record:
                saved = _text(await robot.call_tool("save_recording", {"filename": record}))
                self._log(res, "recording", info=saved)
        return self._finish(res, t0)

    async def _solve(self, robot: Client, tools: list[dict], goal: str, scene: str, res: RunResult) -> None:
        user = f"任务：{goal}"
        if self.mode == "plan":
            plan = self._plan(goal, scene)
            res.planner = plan
            self._log(res, "plan", plan=plan)
            if not plan.get("feasible", True):
                res.final_text = f"规划判断无法完成：{plan.get('reason')}"
                return
            user += "\n计划步骤：" + "；".join(plan.get("steps", []))

        messages = [{"role": "system", "content": EXECUTOR_PROMPT}, {"role": "user", "content": user}]
        res.final_text = await self._executor(robot, tools, messages, res)

        if self.mode in ("verify", "plan"):
            for _ in range(self.max_verify):
                after = _text(await robot.call_tool("get_scene", {}))
                verdict = self._verify(goal, scene, after, res.final_text)
                res.verifier_rounds += 1
                self._log(res, "verify", verdict=verdict)
                if verdict.get("passed"):
                    break
                messages.append({"role": "user", "content": f"校验未通过：{verdict.get('reason')}。请根据最新场景继续完成任务。"})
                res.final_text = await self._executor(robot, tools, messages, res)

    def _finish(self, res: RunResult, t0: float) -> RunResult:
        res.seconds = round(time.time() - t0, 1)
        u = self.llm.usage
        self._log(res, "done", final=res.final_text, tool_calls=res.tool_calls, seconds=res.seconds,
                  model_calls=u.calls, prompt_tokens=u.prompt, cache_hit_rate=round(u.hit_rate, 3))
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACE_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{res.mode}.jsonl"
        with path.open("w") as f:
            for e in res.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        res.trace_path = str(path)
        return res

