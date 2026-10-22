# 工程笔记：动机、难点、解法

面试用。每条按"动机 → 难点 → 解法 → 证据"写，证据是 commit、测试或实测数字，都能在仓库里复现。
计划和里程碑见 `platform-plan.md`。

## 架构

### 现在（单机）

```
LLM harness (bare / verify / plan)          ← agent 侧：规划、工具调用、校验结论 → trace (<run>.jsonl)
        │ MCP (stdio)
        ▼
server.py  工具层：safety gate → skill → observation          ← 环境侧：每次调用写 episode log
        │                                                       (<run>.env.jsonl：观测 + 真值)
        ▼
sim.py     技能 (pick/place) → perception（目标位置估计）→ IK (mink) → MuJoCo
```

关键的分层原则：
- **agent 只看观测，真值只给评分**。观测 = 感知估计 + 本体感知；真值由环境自己记，agent 碰不到。
- **几何在代码里，决策在模型里**。技能和派生事实（`distance_to_tray_m`）确定性计算，模型只选做什么。
- **安全检查不依赖感知**。安全闸只用几何规则，感知错了也挡得住。

### 目标（SaaS）

见 `platform-plan.md` 的架构图：Web → API → Postgres（元数据 + SKIP LOCKED 任务队列）+ S3，
sim worker 每个 episode 一个进程，环境通过 MCP 对外，外部 agent 也能接入。

## 决策记录

### 1. 给 agent 技能而不是关节角

- **动机**：让 LLM 直接输出关节角或末端位姿，基本做不成任务；LLM 擅长选择做什么，不擅长连续控制。
- **难点**：SO-101 只有 5 个自由度，不能到达任意 6-DoF 位姿；方块在夹爪里偏心约 9 mm，偏移方向随腕部转动。
- **解法**：IK（mink）里位置权重高于姿态，残差超过 1 cm 判定够不到；放置时在目标上方实测物体相对指尖的偏移再修正。
- **证据**：`sim.py` 的 `solve_ik`、`place`；`scripts/probe_grasp.py` 实测偏移 9.0 mm 恒定。

### 2. MuJoCo 渲染卡死

- **动机**：MCP 工具里要渲染画面（`look`、录像、实时画面）。
- **难点**：同步工具在 MCP SDK 的工作线程里跑，MuJoCo 的 OpenGL 上下文属于主线程，渲染直接挂住。
- **解法**：所有工具写成 `async`，跑在事件循环所在的主线程上。这条约束后来也决定了 SaaS 的 worker 设计：一个 episode 一个进程。
- **证据**：`server.py` 顶部注释；`CLAUDE.md` Notes。

### 3. 理想仿真区分不了 harness

- **动机**：评测要能比较 harness 设计（bare / verify / plan）。
- **难点**：理想仿真里三种模式都是 10/10，评测没有区分度。
- **解法**：注入静默失败：放进托盘后以概率 p 弹出，但技能照样报成功。分两种：immediate（工具结果里能看到）和 delayed（工具返回之后才发生，结果是过期的，类似真机的感知延迟）。
- **发现**：immediate 时连 bare 都能自己发现并恢复；只有 delayed 才拉开差距。结论是观测准确时，执行者自己就能校验。
- **证据**：README 结果表；commit `7dfd067`。

### 4. 校验者比没有更糟

- **动机**：verify 模式加了一个独立上下文的校验子 agent。
- **难点**：校验者 v1 只看执行后的场景。对"把离托盘最远的方块放进去"，它在剩下的方块里重新找"最远的"，把正确结果判成失败；对不存在物体的陷阱任务，它把正确的拒绝也判成失败。
- **解法**：v2 同时给执行前和执行后的场景，"最远""不要动"都以执行前为准；正确拒绝算通过。原则是校验者要的是事实，不是更多推理。
- **证据**：commit `1ceb5f2`；README 结果表里 v1 和 v2 的对比。

### 5. 回放：怎么证明一次运行能精确复现

- **动机**：要逐步复盘失败，画面、工具调用、校验结论得对得上。之前的 trace 每次工具调用只存一句摘要。
- **难点**：
  - delayed 失败是在下一次观测时才发生的（`settle_pending`）。如果只重放 executor 的调用，漏掉 harness 自己的 `get_scene`，方块就会在别的步骤弹出，回放跟着分叉。
  - "能复现"需要能被检查，不能只是声称。
- **解法**：记录每一次机器人调用，包括 harness 自己的；回放时在新的仿真里按原顺序重跑，逐步比对位置（容差 1 mm）和离散状态（ok、in_tray、holding），报告第一个分叉的步骤。
- **证据**：一次真实的 plan 运行 25/25 步复现；测试里人为篡改一步，能准确定位到那一步（`tests/test_replay.py`）。

### 6. 先测机制，再决定做什么

- **动机**：外部建议是"连续失败 2 次就重规划、调整夹爪角度"，加"视觉感知"。
- **难点**：照字面做，有可能做出摆设。
- **解法**：先实测（`scripts/probe_*.py`），结果推翻了一部分建议：
  - 方块朝向不影响抓取：夹爪闭合时会把方块转正（-45° 变成 22°），所以"调整夹爪角度"对方块是假问题。
  - 随机注入的失败和动作无关，原样重试本来就是最优策略，重规划帮不上忙。真实运行里，红色方块连续 4 次放入后被弹出，Agent 都在原样重试。
  - 抓取位置容差约 6 mm（俯视相机下约 4.6 像素），这是感知误差的上限。
  - 机械臂悬停时会完全挡住目标，抓取过程中俯视相机看不到目标。
  - 纯色方块用颜色阈值就能定位，VLM 的价值在语义（认出是哪个），不在几何。
- **证据**：`platform-plan.md` 里的"Measured mechanisms"表。

### 7. 抓取是否成功：用本体感知，不用真值

- **动机**：原来的 `pick` 用真值判断有没有抓住，真机没有这个信息。
- **难点**：需要一个可靠的物理信号。
- **解法**：看夹爪关节。抓住 24 mm 的方块时，关节停在 +0.08 rad；抓空时一路合到 -0.17 rad。阈值取在两者之间；抓空时返回明确的错误。
- **证据**：`scripts/probe_gripper.py` 在所有偏移下都和真值一致；`tests/test_sim.py`。

### 8. 安全闸

- **动机**：业界的共同做法是在模型输出和执行之间放确定性校验（SafeEmbodAI、RoboGuard）。
- **难点**：规则太严会挡掉合法动作（比如 `place_at` 到托盘里），太松又没意义；而且检查不能依赖感知。
- **解法**：只检查带自由坐标的命令（`move_to`、`place_at`）：工作空间范围、离桌面的最小高度、底座禁区、坐标是否为有限数。被拦下的命令不执行，结果标 `blocked: true`，评测可以统计。
- **证据**：`safety.py`；`tests/test_safety.py`（被拦下时机械臂一动不动）。

### 9. 观测和真值分开，由环境自己记录

- **动机**：原来每个技能都返回真值场景，校验者读的也是真值，评测分数里有"偷看答案"的成分；平台以后要让外部 agent 接入，真值更不能交给 agent 那一侧。
- **难点**：
  - 评分和回放都需要真值，但真值不能出现在 agent 能看到的任何地方。
  - agent 侧的 trace 和环境侧的记录要能逐条对应。
  - 回放时调用同一套工具，不能把正在核对的那份记录覆盖掉。
- **解法**：
  - `sim.observe()`（感知加本体感知；`holding` 只给布尔值）和 `sim.truth()` 分开。
  - 技能瞄准的是感知估计（`Perception` 接口，目前是 oracle），这样以后换成真实检测器，感知误差会自然变成执行失败。
  - 环境写自己的 episode log，每一步记观测和真值；harness 的 trace 只记事件和步骤号，用步骤号对应；评分读 episode log 里的真值。
  - 回放时先把日志挂载断开，再重跑。
- **证据**：commits `5eb3033`、`54b0995`；`tests/test_replay.py::test_episode_log_hides_truth_from_observation`；真实 verify 运行 14/14 步复现。

### 10. 分离之后的评测：分数没变，这是对的

- **动机**：按项目规则，改了工具或 harness 就要在理想和 delayed 两种设置下重跑评测，并照实报告。
- **结果**（Gemini Flash，5 任务 × 2 种子）：理想环境三种模式都是 10/10；delayed（p = 0.5）下 bare 6/10，verify 10/10，plan 10/10。
- **解读**：
  - 感知还是 oracle，观测和真值只差在 `holding` 的粒度上，所以分数不该变。分离的价值是结构上的：M4 换成真实检测器以后，感知误差才会进入分数。
  - 同样的种子，同一天早些时候 bare 是 5/10。每组 10 次，差一次就在噪声范围内。这是 M2 / M5 要做配对比较和 pass^k 的直接理由。
- **证据**：`out/eval-20261022-163223-slip0.0-immediate.json`、`out/eval-20261022-163225-slip0.5-delayed.json`（本地运行产物）；README 结果表。

### 11. 平台骨架（M1）：用 Postgres 做任务队列和多租户

- **动机**：SaaS 需要把实验拆成 episode 分给 worker 跑，并且租户之间要隔离；不想为此多运维一个 Redis。
- **设计**：
  - 队列：episodes 表就是队列，worker 用 `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1` 领任务，同一个 episode 不会被两个 worker 同时领到。
  - 运行中定时写心跳；reaper 把心跳过期的 episode 放回队列，超过最大尝试次数就标为 `error`，不计入评分样本。
  - worker 只能在 `claimed_by = 自己 AND status = 'running'` 时写回结果，被 reaper 回收后迟到的结果会被丢弃。
  - 多租户：每张表带 `org_id`，子表用 `(org_id, parent_id)` 复合外键指向父表，数据库本身就拒绝跨租户引用，不只靠应用层过滤。
  - 版本不可变：suite_versions 和 agent_versions 有触发器禁止 UPDATE；内容 hash 相同的版本直接复用（接口返回 200 而不是 201）。
- **测试抓到的 3 个 bug**：
  - 并发领任务卡死：领到 episode 后还要把 experiment 标成 running，第二个 worker 会在 experiment 的行锁上等第一个 worker 的事务结束。"跳过被锁住的行"的测试因此挂住。修法是这一步也用 `SKIP LOCKED`：别的领取者已经在做同一件事了，不用等。
  - 心跳线程类里定义的 `self._stop` 覆盖了 `threading.Thread._stop`，导致 `join()` 崩溃。worker 主循环把异常记进日志后继续运行，把问题藏住了；是集成测试暴露出来的。
  - 浮点误差让 Wilson 区间在 0/n 时下界是 5.6e-17，而不是 0；在边界上改成返回精确值。
- **还没做**：行级安全（RLS），因为它需要先定几件事：API 用的非 owner 数据库角色、worker 跨租户读取的权限、在知道 org 之前怎么查 API key；真正的 `HarnessRunner`；对象存储上传。都列在 `development.md` 里。
- **证据**：`packages/platform/tests/integration/`，48 个测试跑在真实 Postgres 16 上，测试库每个会话新建、结束后删除；commits `61579a8`、`9c988c7`、`be7fef5`。

### 12. 把环境和平台接起来：HarnessRunner

- **动机**：M0 让环境变"诚实"，M1 搭好了队列和多租户，但 worker 还是个桩，接口建了实验也没有东西去跑。
- **设计**：
  - 环境层面的失败注入（slip）属于场景，放在 suite 的 task 里；模式、模型这些属于 agent，放在 agent_config 里。两者分开版本化，所以"换 agent，场景不变"的对比是干净的。
  - 一个 task 的多次 repeat 共用同一个种子：场景相同，测出来的就只是模型自身的方差，正好是 pass^k 要的。
  - 成功判定读 episode log 里的真值，不看 agent 怎么说；trace 和 episode log 按 `<org>/<project>/<experiment>/<episode>/attempt-<n>/` 存放，并保留原文件名，这样下载下来就能直接回放。
- **难点和解法**：
  - 测试不能依赖网络和 API key，又要覆盖真实的 harness、MCP 子进程和 MuJoCo。做法是 `ScriptedLLM`：按固定剧本返回 tool call，其他部分全是真的。它还能构造出"agent 声称成功、实际失败"的情况（种子 1，delayed slip），证明分数来自真值。
  - MinIO 一直返回 400 "unsupported API call at '/'"：boto3 对自定义 endpoint 默认用 virtual-host 风格，把桶名放进了域名，改成 path 风格就好了。
  - 第一次端到端运行时，worker 先跑了开发库里另一个组织残留的 4 个 episode：claim 是全局先进先出，一个租户的积压会饿死其他租户。已经记进待办：按组织轮转领取，并给每个组织设并发配额。
- **证据**：端到端运行（真实 Gemini、Postgres、MinIO），红色方块 + delayed slip，种子 1、2：bare 1/2（Wilson [0.09, 0.91]），verify 2/2（[0.34, 1.00]）；从 MinIO 下载下来的产物回放 12/12 步复现。`tests/integration/test_harness_runner.py`（5 个测试）。

### 13. 统计：怎么判断"真的变差了"

- **动机**：README 里 bare 一天之内跑出过 5/10 和 6/10；端到端 demo 里 1/2 的 Wilson 区间是 [0.09, 0.91]。只看成功率，没法判断一次改动有没有让 harness 变差。
- **设计**：
  - **配对比较**：两个实验按（task, seed, repeat）对齐，场景完全相同；只有一边成功的"不一致对"才算证据，用精确 McNemar 检验（对不一致对做二项检验）。这样消除了"场景难易不同"带来的方差，同样的样本量下比两个独立成功率的比较更灵敏。
  - **判定规则**：p < 0.05 才判为 regression 或 improvement，否则是"没有显著差异"。比如 6 个不一致对全部偏向一边，p = 2/64 ≈ 0.031，判回归；5 个不一致对、比例 1:4，p > 0.05，不足以下结论。
  - **pass^k**（τ-bench 的无偏估计 C(c,k)/C(n,k)）：衡量的是可靠性，不是 k 次里至少成功一次。repeat 共用种子，所以它测的是模型自身的方差。比如 4 次里成功 3 次，pass^1 = 0.75，pass^4 = 0。
  - 两个实验的 suite 版本不同时，接口会标出来，因为同一个 task key 背后的任务可能已经变了。
- **证据**：`stats.py`、`results.py`；`tests/unit/test_stats.py`、`tests/integration/test_read_api.py`。

### 14. 队列公平性，以及一个写错的测试

- **动机**：第 12 条发现全局先进先出会让一个组织的积压饿死其他组织。
- **解法**：领任务时，先选正在运行的 episode 最少的组织，再在组织内按创建时间先后取；可选每组织并发上限 `ROBOMCP_MAX_RUNNING_PER_ORG`。这个上限是"软"的：两个 worker 同时领任务时，可能都看到某组织还差 1 个到上限，结果都领到了。要做成硬上限，每次领任务都得加一把组织级的锁，代价不值得，所以选了软上限，并写进了注释。
- **踩坑**：我写的"组织内按顺序领取"测试 5 次里失败了 4 次。原因是同一个实验的 episode 是一条 INSERT 插入的，`created_at` 完全相同，排序退回到随机的 UUID。这不是代码的 bug，是测试的假设错了：真正要保证的是"组织内先建的实验先跑"，测试按这个改了，之后连续跑 5 次全部通过。教训是：测试不稳定时，先确认它到底在断言什么。
- **证据**：`queue.py` 的 `_CLAIM_SQL`；`tests/integration/test_fair_queue.py`。

### 15. 在入口处校验，不在 worker 里失败

- **动机**：写错的任务配置（不存在的检查名、slip = 1.5）原来要等到 worker 运行时才报错，而且会被当成基础设施故障重试 3 次。
- **解法**：建 suite 版本和 agent 版本时就校验，不合法直接返回 422：检查名必须是内置的，失败注入只允许 `slip ∈ [0, 1]` 和 `slip_mode ∈ {immediate, delayed}`，`mode` 只能是 bare / verify / plan。已有的队列测试用的是假任务名，我给它们补上了真实存在的检查，没有为了让测试通过而放宽校验。
- **证据**：`api/schemas.py`；`tests/integration/test_experiments.py`。

## 面试可能问到的

- **为什么不让 LLM 直接控制关节？** 见第 1 条。分层（System 2 规划 + System 1 执行）也是业界主流（Gemini Robotics-ER + VLA、π0.5、GR00T N1）。
- **怎么知道 harness 改动是真变好，还是随机波动？** 在相同种子上做配对比较，配合 pass^k 和 Wilson 区间（M2/M5）；回放能证明环境侧是确定的，所以剩下的方差只来自模型。
- **怎么防止 agent "作弊"？** 见第 9 条：真值由环境自己记录，agent 只能拿到观测。
- **一个失败是谁的错？** 用真值逐层比对：感知估计误差超过 6 mm 算感知错，选错目标算规划错，目标对但没抓住算执行错（M4）。
