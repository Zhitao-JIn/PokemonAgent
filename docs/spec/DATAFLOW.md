# 数据流规格（DATAFLOW）

> 全项目数据怎么流动的完整规格：**两级 harness**（run 主 agent / episode 子 agent）、
> **三条通道**（调用 / trace / memory），以及每一跳的数据形状与**全部字段**。
>
> 与 `harness/SPEC.md`（单 episode 六节点图的逐节点详解）互补：那份讲"一局内部怎么跑"，
> 这份讲"整个 run 的数据从哪来、到哪去、长什么样"。

## 0. 总览

```
┌────────────────────────────────────────────────────────────────────────┐
│ RunHarness（主 agent，一 run = 完整一局 Pokemon 游戏）                    │
│                                                                         │
│   RunState                                                              │
│   begin → plan → dispatch → reflect → (栈空/结束 → END | 否则 → review)    │
│                                          review ──(继续/重试/压目标 → plan │
│                                                  | 停止 → END)           │
└────────────────────────────────────────────────────────────────────────┘
      │ 通道① 调用（同步）                 ▲ 通道② Trace（mask 读）
      │ run(episode_id, 栈顶, 全栈)        │ events(RUN_TRACE_MASK)
      │ → HarnessEpisodeOutcomeResp        │ 同一实例：episode 写、run 读
      ▼                                   │
┌────────────────────────────────────────────────────────────────────┐
│ EpisodeHarness（子 agent，一 episode = 解决栈顶一个目标）              │
│                                                                     │
│   EpisodeRunState                                                   │
│   look ──(observation.done ?)──→ summarize → END                    │
│     └─(else)→ retrieve_memory → think → press → remember → look     │
└────────────────────────────────────────────────────────────────────┘
      │                                   │ 通道③ Memory（共享实例）
      ▼                                   ▼
   World（PyBoy + VLM）            Memory（三种记忆，md+frontmatter 落盘）
```

**三层认知**：

- **run** = 完整一局游戏（`run_id` 是会话标识，世界只装配一次）；维护**目标栈**，
  每层一个 episode；弹栈/压栈/重压是它的职责（`reflect`）。
- **episode** = 只解决**栈顶一个目标**；判成即本局结束，不自己决定下一步。
- **三条通道**：① 调用是唯一的显式握手；② trace 是 episode 写给 run 读的事实来源；
  ③ memory 是双方共享的存储，跨 episode 连续性由它保证。

---

## 1. 通道①：调用协议（run ↔ episode）

### 1.1 两端的接口

```python
# run 级（主 agent）
HarnessPort.run(run_id: str, goals: list[TaskForHarness]) -> RunOutcomeResp
    # 节点：begin → plan → dispatch → reflect → review（大图，LangGraph）

# episode 级（子 agent）
EpisodeHarnessPort.run(
    episode_id: str,
    task: TaskForHarness,        # 栈顶目标（执行单元）
    stack: list[TaskForHarness], # 整个目标栈（全局信息，投影成 goals）
) -> HarnessEpisodeOutcomeResp
    # 节点：look → retrieve_memory → think → press → remember（循环）
    #        + summarize（收尾）
```

### 1.2 RunState（run 级，大图上流转的全部状态）

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | `str` | 这次 run 的标识（完整一局游戏会话），trace 按它分组 |
| `goals` | `list[TaskForHarness]` | 目标栈，**栈顶 = `goals[-1]`**（下一个要解决的） |
| `outcomes` | `list[HarnessEpisodeOutcomeResp]` | 已完成的 episode 结算，按执行顺序——`RunOutcomeResp` 的汇总源 |
| `episode_id` | `str \| None` | 本轮派发的 episode 标识（dispatch 写入） |
| `outcome` | `HarnessEpisodeOutcomeResp \| None` | 本轮刚收的结算（reflect 弹栈的依据） |
| `last_task` | `TaskForHarness \| None` | 刚派发的那一层目标（review 的 RETRY 决策压回栈顶用） |
| `done` | `bool` | run 是否结束（栈空 / 主 agent 判断该停 / 人类停止） |
| `why` | `str` | 结束原因（"全部目标解决" / "目标栈耗尽" / "human stopped"） |

**活对象（episode harness / trace / memory / llm / reviewer）不进 state**——
序列化不了，是 `RunHarness` 的构造参数，装配时注入。

### 1.4 human-in-the-loop（review 节点，每个 episode 之间）

`reflect` 收完结算、弹栈后，**栈非空时**进入 `review` 节点：调 `HumanReviewer`
（注入接口，默认 `AutoContinueReviewer` 永远继续；**前端接入后替换**），
把 `HumanReviewReqFromHarness`（run_id / 已完成结算 / 当前栈 / 刚跑完的目标）交给人类，
按 `HumanReviewRespFromFrontend` 路由：

| 决策 | 效果 |
|---|---|
| `CONTINUE` | 继续下一层（→ plan） |
| `STOP` | 置 done，结束 run（→ END，why = "human stopped"） |
| `RETRY` | 刚跑完的那一层压回栈顶（→ plan） |
| `PUSH` | 新目标追加到栈顶之后，先做新目标（→ plan） |

协议见 `schemas/communication/human_review.py`（`HumanReviewReqFromHarness` / `HumanReviewRespFromFrontend` /
`HumanDecision`），接口见 `interfaces/harness/human_reviewer.py`。

### 1.3 EpisodeRunState（episode 级，小图上流转的全部状态）

| 组 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 身份（跨步） | `episode_id` | `str` | 全局唯一，trace 按它分组 |
| | `task` | `TaskForHarness` | 在跑哪个任务（目标/判据/步数上限） |
| | `step` | `int` | 第几步。**全项目只有这一个 step**，max_steps 是一道闸 |
| | `goals` | `list[GoalForBrain]` | 目标栈（run 级投影）。**判只判栈顶 `goals[-1]`**，全程只读 |
| 流转（单步） | `observation` | `ObservationFromWorld \| None` | 当前帧（盖章后的） |
| | `action_space` | `ActionSpaceForBrain \| None` | 此刻能按的键（look 算好，think 消费） |
| | `memories` | `list[StepMemory]` | `retrieve_memory` 查出的情景记忆 → `think` |
| | `action` | `ActionFromBrain \| None` | `think` 产出 → `press` 消费 |
| | `pending_observation` | `ObservationFromWorld \| None` | 还没盖章的新观测（`press`/`begin` 产出 → `look` 消费） |

**`outcome` 不在 state 里**——由 `run()` 在图跑完后从 `observation` 直接算。

### 1.4 目标栈投影（两级栈的关系）

```
run 级：  goals = [TaskForHarness(t3), TaskForHarness(t2), TaskForHarness(t1)]
                                                          └─ 栈顶，先做
dispatch 时把全栈传给 episode：
episode： goals = [GoalForBrain(goal=t3.goal, criteria=t3.criteria),   ← 全局信息
                   GoalForBrain(goal=t2.goal, criteria=t2.criteria),
                   GoalForBrain(goal=t1.goal, criteria=t1.criteria)]  ← 栈顶，判它
```

- **判只判栈顶**：`judge(goal=goals[-1])`；判成即本局结束（done+success）。
- **弹栈/压栈/重压是 run 级 `reflect` 的事**——episode 不碰。
- 栈顶先解决的语义：初始栈 `goals[-1]` 第一个被派发。

### 1.5 异常传递

| 异常 | 谁处理 | 结果 |
|---|---|---|
| `AgentError`（MaxRetriesExceeded 等预期失败） | run 级 `dispatch` 捕获 | 包装成 `success=False, steps=0, reason="error: Xxx"` 的结算，run 继续 |
| 其他异常（代码 bug 等） | 不捕获 | 上抛，整个 run 中断——吞掉会产假数据 |

### 1.6 结算形状

**HarnessEpisodeOutcomeResp**（episode → run）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `episode_id` | `str` | 这一局的标识 |
| `success` | `bool` | 成没成 |
| `steps` | `int` | 实际用了多少步 |
| `reason` | `str` | 终止原因：`success` / `max_steps_exceeded` / `world_ended` / `error: Xxx` |

**RunOutcomeResp**（run → 调用方）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | `str` | 这次 run 的标识 |
| `outcomes` | `list[HarnessEpisodeOutcomeResp]` | 每个 episode 的结算，按执行顺序 |
| `total` | `int` | 跑了多少个 episode |
| `succeeded` | `int` | 其中成功几个 |
| `success_rate` | `float` | 成功率（0.0–1.0），run 级自己算好 |

---

## 2. 通道②：Trace 事件流

### 2.1 信封（五元组）

```
(episode_id, step, EventType, Source, payload)     ← TracePort.append 的五个位置参数
```

- `episode_id` 在位置参数（trace 按它分组落盘 `{episode_id}.jsonl`），**payload 不重复记**。
- `step`：发生在第几步。
- `Source`：事件由哪一层产生（横切，不放 payload，因为每种聚合几乎都按它切）：

| Source | 含义 |
|---|---|
| `PERCEPTION` | 视觉模型这条链（感知） |
| `DECISION` | 文本模型这条链（决策） |
| `HARNESS` | 掩码、生命周期、图控制（不含记忆，记忆统一挂 `MEMORY`） |
| `WORLD` | 模拟器（按键执行） |
| `JUDGE` | 成败判定（和决策分开记账，才算得出它自己的准确率） |
| `VERIFY` | step 记忆校验（蒸馏前把关）——0902 从 `JUDGE` 拆出来独立记账，混在一起
  时两条链的 token/延迟分不开，算不出校验器自己的失效率 |
| `MEMORY` | 记忆子系统整体：四类检索（`MEMORY_READ`）、三类写入
  （`STEP_MEMORY_WRITE`/`OBJECT_MEMORY_WRITE`/`EPISODE_MEMORY_WRITE`）、
  跨局摘要蒸馏这条模型调用 |
| `PLAN` | run 级规划器（`RunHarness.plan`）——和 episode 内的 `DECISION` 是两条
  不同的模型链，以前误挂在 `HARNESS`（本该是零成本记账），会让"harness 花了
  多少 token"这个聚合数字失真 |

**0903 type 收敛（第三版 schema，`TRACE_SCHEMA_VERSION=3`）**：type 只保留与
生产者正交的种类，数量从 20 收敛到 **7**；原 20 类的语义全部降级为
`payload.kind`（词汇表见下表）。`Source` 仍是 8 个成员。**v2 及更早的 JSONL
（type 值为 observe/think/retrieve…）不再可解析**——这是收敛时明确接受的结果。

### 2.2 事件总表（7 类，与 source 正交，无兼容成员）

| type（payload.kind 词汇） | 内容 | 常见 Source |
|---|---|---|
| `model_call` | 一次模型交互的账：tokens/延迟/attempt/ok/raw（六链共用，`depth`/`why`/`verdicts` 等随 payload） | perception/decision/judge/verify/memory/plan |
| `error` | 一个失败；`kind` 给模式、`reason` 给细节 | 各自链 |
| `llm_outcome`（intent/verdict/audit） | LLM 产物：intent=think 的动作意图（action/thought/rationale）；verdict=judge 成败结论（done/success/stalled/depth/why）；audit=verify 校验汇总（checked/unreliable，逐条 verdicts 在对应 model_call） | decision/judge/verify |
| `view`（frame/after） | frame=每条链首一条 `OBSERVE`（完整 facts + goals + **这一链开局的帧**）；after=`perceive_after_action` 的 `AFTER_ACTION` 轻量摘要（只含 RAM 档读得出的 status/done，链内每键一条）；链尾键的帧挂在它自己的 `AFTER_ACTION` 上，下一条链的 `OBSERVE` 按 event_id 读回同一张图（§1.5 订正） | perception |
| `act`（space/executed/stall） | space=get_action_space 掩码（count/names）；executed=世界真按的动作链；stall=停摆护栏快照（stall_key/count） | harness/world |
| `memory_io`（read_merge/read_step/read_global/read_knowledge/read_object/read_verify_steps/read_verify_knowledge/write_step/write_object/write_episode） | read_merge=主循环四路合并读全文（含 known_objects_text 等）；read_*=各检索命中摘要（count/refs）；write_*=三类记忆写入（content/完整副本） | memory |
| `lifecycle`（run_start/run_end/episode_start/episode_end/step） | run 与 episode 边界（run 级 `episode_id` 放 run_id、step=0）+ step 刻度推进 | harness |

**判定式**：给一条事件换一个生产者，type 不变 → type 正交成立。能天然跨
source 的只有 `model_call`/`error`；`llm_outcome` 横跨 decision/judge/verify
三条 LLM 链，`act` 横跨 harness/world；view/memory_io/lifecycle 是"领域本质
单源"的产物种类（种类名描述记录相对世界/模型的位置，不是写它的节点）。

**动作的两个面**：intent（打算按）+ executed（按下了）用同一个
`action_chain()` 拼 payload——形状一致才能直接 diff。**动作的结果不记**：
按完之后世界变成什么样，答案是下一条 `view/frame` 里那份完整观测（结果是
观察，不是描述）。

### 2.3 run 级 mask 读取（读取即过滤）

```python
RUN_TRACE_MASK = frozenset({
    EventType.LIFECYCLE, EventType.ERROR,
})   # 0903 后粒度在 kind：history_lines 内再按 payload.kind 筛 episode 边界
trace.events(RUN_TRACE_MASK)   # 只读高层决策信号，噪声读取时就滤掉
```

| 读（plan/reflect 的思考依据） | 为什么 |
|---|---|
| `lifecycle`（kind=episode_start/episode_end） | 每局边界 + 成败（做了哪些尝试、各成各败） |
| `error` | 失败模式（为什么败） |
| （如需每局蒸馏经验：`memory_io` kind=write_episode，已浓缩，不需要再从 memory 查） |

| 不读 | 为什么 |
|---|---|
| `view` | 帧详情（facts 全量）——run 级不需要"某帧看到什么" |
| `model_call` | 账（tokens/raw）——成本统计不是规划信号 |
| `llm_outcome`(intent) / `act`(executed) | 单步决策/执行明细——蒸馏摘要已覆盖，且 thought 原文太长 |
| `memory_io` 其余 read_*/write_* | 单步记忆读写明细 |

**无 trace_cursor**：run 级每次决策读完整历史（按 mask 过滤后每局只剩 ~5 条高层事件），
不增量读。

---

## 3. 通道③：Memory（共享实例）

两个 harness 注入**同一个 `MemoryTool`**：episode 的 `summarize` 蒸馏写跨局摘要，
下一局的 `retrieve_memory` 自动检索到——run 级不直接查，跨 episode 连续性由共享
实例天然保证。

### 3.1 三种记忆的字段

**StepMemory**（一步 = 一条，本局全量按序喂决策）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `before` | `ObservationFromWorld` | 做决定时看到的画面（完整观测） |
| `rationale` | `list[str]` | 当时的理由（不是完整推理——那留在 trace） |
| `action` | `str` | 选了什么，含连按次数，如 `right ×2` |
| `after` | `ObservationFromWorld` | 执行之后的画面（结果也是一次观察） |
| `step` | `int` | 写入时所处的步数 |
| `episode_id` | `str` | 这条经验来自哪一局 |

**EpisodeMemory**（一整局 = 一条，跨局按相关性挑回）：

| 组 | 字段 | 说明 |
|---|---|---|
| 来源 | `episode_id` / `run_id` / `goal` / `success` / `steps` | 这一局是谁、成没成、几步 |
| 本体 | `summary` / `reusable_patterns` / `critical_decisions` / `failure_points` | 蒸馏出的经验（浓缩） |
| 质量 | `quality_score` / `quality_rationale` | 自评分数 + 理由（理由渲染进 `render()`，是排序信任的依据） |
| 索引 | `applicable_scenes` / `tags` | 场景过滤 / 标签 |
| 落盘 | `filename` / `markdown` | 存成 `{filename}.md` 的文件名 + 主内容 |

**ObjectMemory**（一格 = 一条，域内恒真，按 `place.key` 存取）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `landmark` | `LandmarkInWorld` | 这一格是什么（kind + place） |
| `touched` | `int` | 互动过几次 |
| `lines` | `list[str]` | 滚动文本窗口（对话/招牌内容） |
| `attempts` | `dict[str, str]` | 姿势 → 结果 的档案 |

### 3.2 检索触发点（7 类，清理后 2 个实际触发口）

| # | 触发时机 | 调用 | 查什么 | 结果去哪 |
|---|---|---|---|---|
| 1 | 每步循环（`retrieve_memory` 节点） | `query_episode_steps(ep)` | 本局单步全量 | `state.memories` → `DecisionReq.memories` |
| 2 | 同上 | `query_objects(obs)` | 语义 object（按当前地图） | `obs.facts["known_objects"]` |
| 3 | 同上 | `query_knowledge(task.goal)` | 知识库（按目标相关性） | `obs.facts["knowledge"]` |
| 4 | 同上（条件：`obs.place` 非空） | `query_episode_summaries(scene, goal)` | 跨局摘要（场景过滤 + 目标检索） | `obs.facts["episode_memories"]` |
| 5 | 判定时（`_judge` 内部） | `query_recent_steps(ep, JUDGE_HISTORY_KEY_CAP)` 再按链裁 | 本局**最近 2 条链**（`JUDGE_CHAIN_HISTORY`；`JUDGE_HISTORY` 是 0905 的旧名，单位是步） | 判定模型的 history（**不走 retrieve 节点**——两条独立检索链）。**订正 2026-09-12**：粒度下沉到单键后按步取会把视野除以链长，改为按链取 |
| 6 | 蒸馏时（`summarize`） | `query_episode_steps(ep)` | 本局全量 | 蒸馏器输入（读，不算检索） |

### 3.3 三层存储（EpisodeMemory）

```
{filename}.md（唯一真相）
──────────────────────
---                    ← JSON frontmatter（全部元数据字段，EpisodeMemory 除 markdown 外）
{episode_id, summary, reusable_patterns, ...}
---
{LLM 生成的 markdown 正文}   ← 主内容（人读）
──────────────────────

trace 的 EPISODE_MEMORY_WRITE   ← 完整副本（trace 格式），run 级读每局经验
内存索引                        ← 启动时扫描 .md 目录解析 frontmatter 重建 → embedding/检索
```

- **md 是主内容，元数据挂 md 上**（`FileEpisodeMemoryStore` 写 = frontmatter+正文，
  读 = 启动扫描目录重建，旧纯正文 md 跳过不崩）。
- **落盘目录 = `memory/episode/memory/`（包内，但 gitignore 不进版本库）**——它是
  agent 运行期产物；`semantic/knowledge/*.md` 是运营手写内容，留在仓库。
- 单步记忆（StepMemory）不单独落盘文件——走内存 + trace 的 `STEP_MEMORY_WRITE` 副本。

---

## 4. 一次 run 的完整时序（字段级）

以 3 层目标栈 `[t3, t2, t1]`（栈顶 t1 先做）为例：

```
run("run1", [t3, t2, t1])
│
├─ begin：RunState{run_id="run1", goals=[t3,t2,t1], outcomes=[]}   ✓ 校验
│
├─ plan：静态（读 trace 的入口预留，栈非空就派发）
│
├─ dispatch：
│    episode_id = "run1-ep1"
│    outcome = episode.run("run1-ep1", t1, [t3,t2,t1])
│    │
│    │  ┌─ _begin：EPISODE_START{goal=t1.goal, max_steps} 写 trace
│    │  │    goals 投影 = [GoalForBrain(t3), GoalForBrain(t2), GoalForBrain(t1)]
│    │  │    pending_observation = world.reset(task) 的第一帧
│    │  │
│    │  ├─ look：盖章（step/done）→ OBSERVE{status,scene,overlay,facts,goals}
│    │  │         → judge 判栈顶（MODEL_CALL{...depth, why}）→ action_space 进 state
│    │  │
│    │  ├─ retrieve_memory：四类查询 → MEMORY_READ{count,refs,known_objects_text,...}
│    │  │         → state.memories
│    │  │
│    │  ├─ think：choose(goals, obs, action_space, memories)
│    │  │         → MODEL_CALL{DECISION 账} + THINK{action,sequence,thought,rationale}
│    │  │         → state.action
│    │  │
│    │  ├─ press：execute(action) → ACT{action,sequence}（与 THINK 同形）
│    │  │         → pending_observation = 链尾感知帧
│    │  │
│    │  ├─ remember：reflect(before, action, after) → STEP_MEMORY_WRITE{ref,content}
│    │  │         + OBJECT_MEMORY_WRITE{key,kind,content} → 写共享 memory
│    │  │
│    │  └─ （循环 look…，直到 done）
│    │
│    └─ summarize：蒸馏 → MODEL_CALL{MEMORY 账} + EPISODE_MEMORY_WRITE{全字段}
│                   → FileEpisodeMemoryStore 落 md+frontmatter（共享 memory）
│
│    ← HarnessEpisodeOutcomeResp{episode_id="run1-ep1", success, steps, reason}
│
├─ reflect：outcomes=[ep1 结算]，弹栈 goals=[t3,t2]，last_task=t1
│
├─ review：栈非空 → 调 HumanReviewer（HumanReviewReqFromHarness{run_id, outcomes×1, goals=[t3,t2], last_task=t1}）
│           默认 AUTO_CONTINUE → 继续
│
├─ dispatch：episode.run("run1-ep2", t2, [t3,t2]) …（同上，栈长 2）
├─ reflect：outcomes=[ep1, ep2]，弹栈 goals=[t3]，last_task=t2
│
├─ review：栈非空 → 人类（举例）选 PUSH{p1} → goals=[t3, p1]（p1 先做）
│
├─ dispatch：episode.run("run1-ep3", p1, [t3, p1]) …（栈长 2）
├─ reflect：outcomes=[ep1, ep2, ep3]，弹栈 goals=[t3]
│
├─ dispatch：episode.run("run1-ep4", t3, [t3]) …（栈长 1）
├─ reflect：outcomes=[ep1, ep2, ep3, ep4]，弹栈 goals=[] → done=True, why="全部目标解决"
│
└─ run() 组装：RunOutcomeResp{run_id, outcomes×4, total=4, succeeded=N, success_rate=N/4}
```

**每个节点的产物都进 state 或 trace，不藏私**——读图就能还原任何一局发生了什么、
每一步数据长什么样。
