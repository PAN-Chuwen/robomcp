"""没有 function calling 时，怎么让模型"自己干活"：让它按格式写字，再用正则把字解析出来。

离线可跑（模型回复是写死的示例）：python3 loop_before_function_calling.py
"""

import re

# ---- 一个玩具世界：三个方块，一个托盘 ----
world = {"red_cube": "table", "green_cube": "table", "blue_cube": "table", "holding": None}


def pick(name):
    if world["holding"]:
        return f"失败：手里已经拿着 {world['holding']}"
    world["holding"], world[name] = name, "gripper"
    return f"成功：拿起了 {name}"


def place_in_tray():
    name = world["holding"]
    if not name:
        return "失败：手里是空的"
    world[name], world["holding"] = "tray", None
    return f"成功：{name} 放进了托盘"


FUNCS = {"pick": pick, "place_in_tray": place_in_tray}

# ---- 提示词里"教"模型按固定格式输出 ----
PROMPT = """你可以使用这些动作：pick(物体名)、place_in_tray()
每次只输出一行，格式必须是：ACTION: 动作名(参数)
全部完成后输出：DONE"""

# 假装是模型的回复（真实情况是调用大模型 API 拿到的文字）
FAKE_MODEL_REPLIES = iter([
    "好的，我先抓红色方块。\nACTION: pick(red_cube)",
    "ACTION: place_in_tray()",
    "Action: pick( 'green_cube' )",   # 模型没严格按格式写：大小写、引号、空格都不一样
    "DONE",
])


def call_model(history):
    return next(FAKE_MODEL_REPLIES)


history = [PROMPT, "用户：把红色和绿色方块放进托盘"]
while True:
    reply = call_model(history)                 # 1. 模型输出一段文字
    print("模型说：", reply.replace("\n", " / "))
    history.append(reply)
    if "DONE" in reply:
        break
    m = re.search(r"ACTION: (\w+)\((\w*)\)", reply)   # 2. 我的代码用正则"读"出它想做什么
    if not m:
        result = "格式错误，没看懂你要做什么"            # 3. 读不出来就只能报错让它重写
    else:
        name, arg = m.group(1), m.group(2)
        result = FUNCS[name](arg) if arg else FUNCS[name]()
    print("   执行结果：", result)
    history.append("结果：" + result)              # 4. 把结果写回对话，再问模型
print("最终世界：", world)
