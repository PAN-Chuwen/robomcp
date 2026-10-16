"""有了 function calling 之后：模型直接给出结构化的调用，代码不用再猜。

需要 Anthropic API 凭据（ANTHROPIC_API_KEY 或 `ant auth login`）：
    uv run --with anthropic python examples/loop_with_function_calling.py
"""

import json

import anthropic

# ---- 同一个玩具世界 ----
world = {"red_cube": "table", "green_cube": "table", "blue_cube": "table", "holding": None}


def pick(object_name):
    if object_name not in world:
        return {"ok": False, "message": f"没有 {object_name} 这个物体"}
    if world["holding"]:
        return {"ok": False, "message": f"手里已经拿着 {world['holding']}"}
    world["holding"], world[object_name] = object_name, "gripper"
    return {"ok": True, "scene": world}


def place_in_tray():
    name = world["holding"]
    if not name:
        return {"ok": False, "message": "手里是空的"}
    world[name], world["holding"] = "tray", None
    return {"ok": True, "scene": world}


FUNCS = {"pick": pick, "place_in_tray": place_in_tray}

# ---- 1. 用 JSON Schema 告诉模型有哪些工具（不再靠提示词"教格式"） ----
TOOLS = [
    {
        "name": "pick",
        "description": "从桌上抓起一个物体。手里已经有东西时会失败。",
        "input_schema": {
            "type": "object",
            "properties": {"object_name": {"type": "string", "description": "例如 red_cube"}},
            "required": ["object_name"],
        },
    },
    {
        "name": "place_in_tray",
        "description": "把手里的物体放进托盘。",
        "input_schema": {"type": "object", "properties": {}},
    },
]

client = anthropic.Anthropic()
messages = [{"role": "user", "content": "把红色和绿色方块放进托盘"}]

while True:
    # 2. 调模型：把整份对话 + 工具列表发过去
    response = client.messages.create(
        model="claude-opus-5-5", max_tokens=16000, tools=TOOLS, messages=messages
    )
    messages.append({"role": "assistant", "content": response.content})

    # 3. stop_reason 告诉你模型这次是"说完了"还是"想调工具"
    if response.stop_reason != "tool_use":
        print("模型最后说：", next((b.text for b in response.content if b.type == "text"), ""))
        break

    # 4. "读调用"：直接从结构化的 tool_use 块里取名字和参数，不用正则
    results = []
    for block in response.content:
        if block.type != "tool_use":
            continue
        print(f"模型要调用 {block.name}，参数 {block.input}（id={block.id}）")
        out = FUNCS[block.name](**block.input)          # 5. 执行的是我的代码
        print("   执行结果：", out)
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,                    # 6. 用同一个 id 把结果对回去
            "content": json.dumps(out, ensure_ascii=False),
            "is_error": not out["ok"],
        })
    messages.append({"role": "user", "content": results})   # 7. 结果塞回对话，进入下一轮

print("最终世界：", world)
