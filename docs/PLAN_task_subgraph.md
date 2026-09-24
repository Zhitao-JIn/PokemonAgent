**状态（0923）：本计划已全部落码——P1=187（episode 压格）、P2=188（task 层）、P3=189（记忆阶梯）、P4=190（run 对齐）、P5=191（账面收尾，本文件随之定格）。下文保留设计过程。**

# PLAN —— task 子图：第三层（run → episode → task）

> 2026-09-22 设计讨论定案。**形状已由用户拍板：task 是第三张子图，不是 episode 内的组件。**
> 理由（用户原话归纳）：episode 作为图拥有一等公民的全部待遇——自己的 state、自己的
> 步骤上限、自己的路径账、自己的 gate——task 是同等的语义执行单元（"点击关闭"这类
> 宏观步），该以同样方式拥有这些，而不是被削成 act 里的一个执行段。
> **改动方向：修改 episode 去承载 task，不修改 task 去迁就 episode。**

## 一、为什么是第三张图（定案理由，留档）

1. **对称性**：run=plan、episode=skill、task=mcp 式具体执行。run 用 `plan` 压意图、
   逐条派发 episode；episode 用同样模式派发 task。全仓只有一种"父子图"模式要学。
2. **框架服务**：子图自带 recursion_limit（task 自己的步数上限由框架闸门兜底）、
   自己的 Pydantic state（交界键有类型校验的基调）、将来可中途 checkpoint/interrupt。
3. **账目独立**：task 的路径记录、token 统计、reward 以"图"为单位成立——不是从
   episode 的账里切出来的一段。

## 二、目标形状

```
RunRuntime（不动）
└─ EpisodeRuntime（改：嵌套持有 TaskRuntime）
   └─ TaskRuntime（新，harness/task/task_runtime.py）
      ├─ provider 路由表：{task_kind → provider 链}   ← 按任务类型重组装 LLM
      ├─ 预算缺省（按 kind 的 max_steps 缺省）
      └─ trace / game 引用（共享实例，同 EpisodeRuntime 模式）

episode 图（改）
  think_action → [路由：本步走 task？]
                   ├─ 否 → act → perceive → close_step（现管道，不动）
                   └─ 是 → task 格（新增，形态 B 手工 invoke 子图）
                            ├─ 组装 TaskInput
                            ├─ invoke(task_graph, context=runtime.context.task)
                            ├─ 收 TaskOutput → state.step += steps_used（对账）
                            └─ 汇合回 store / judge

task 子图（新，harness/task/）
  begin_task（TASK_START + 初始化）
  → [sense → act_key → perceive_light → gate_task]*   ← JEV / 小快模型策略口
  → end_task（TASK_END + 组装 TaskOutput）
```

- **粒度（甲）**：TaskRuntime 一次 run 一份、跨 task 复用，`build.py` 一处装配
  （铁律 3）。每次调用的可变数据全在 task state，不进 runtime。
- **终止全机械**（gate_task）：脚本完成信号 / 自己的 max_steps（recursion_limit 兜底）/
  世界信号。**v1 task 图内没有模型 judge**——0922 刚把"该不该停"收敛成机械闸门，
  task 层不开新的模型决策口；JEV/小快模型是 act_key 位置的**策略口**，不是 judge。

## 三、交界契约（镜像 EpisodeInput / EpisodeOutput）

| | 下行 `TaskInput` | 上行 `TaskOutput` |
|---|---|---|
| 字段 | task 描述（宏观步语义："点击关闭"）、kind、max_steps、初始观测引用 | `result`（成败/结局信号）、`steps_used`、`reward`（MC 归账用）、路径摘要 |

**两个硬契约**（进实现的后置条件 assert）：

1. **`steps_used` 对账**：task 子图内的按键不经过 episode 的 `close_step`，
   `state.step` 不会自己动。`task` 格收到的 `TaskOutput.steps_used` **必须**加回
   episode 的 `step`，否则 judge 的 `max_steps` 判据无声失效（超预算不报错地继续跑）。
   task 自己的计数与 episode 的计数**各自独立**（同 run/episode 现状），对账只在交界处。
2. **MODEL_CALL 必经统一记账**：task 图内所有 LLM 调用走 tool 层那套 `MODEL_CALL`
   账包装，不许直连 provider 不写账。span 内 token 统计 = 对 span 范围求和；
   按 kind 聚合 → "哪类任务用哪个 provider 划算"直接可查，喂回路由决策。

## 四、trace 契约

- **不另开存储**（铁律 6：trace 是 replay / checkpoint / 成本统计的共同底座）。
- 新增两个 kind：`TASK_START` / `TASK_END`（边界）。
- task 范围内全部事件 meta 带 `task_id`；按 task_id 一次拉出完整路径：
  按键序列 + 轻感知摘要 + 结局 + reward。
- **一条完成的任务路径 = 机制二 skill library 的候选种子**——这是路径账"单独成立"的
  真正价值。
- task 内圈感知用**轻量化**路径（帧差/局部 OCR 类），不复用 vision 20s 重管道；
  span 内不写 step 记忆章节（信用落语义步，不落方向键），`end_task` 写一条带语义
  描述的章节。

## 五、改动清单

| 组 | 内容 |
|---|---|
| 新增 | `harness/task/`：`task_runtime.py`、`task_state.py`、`task_graph.py`、`task_entry.py`、节点（begin/act_key/perceive_light/gate_task/end_task）、交界模型 `TaskInput`/`TaskOutput` |
| episode 侧（改） | `episode_runtime.py` 嵌套 `task` 字段；`episode_state.py` 加 task 相关字段；episode 图加路由分支与 `task` 格（形态 B，镜像 `run/nodes/episode.py`）；`think_action` 产出路由意图 |
| 装配 | `build.py` 造 TaskRuntime（provider 路由表按 kind）；`harness/__init__.py` 出口 |
| trace | `TraceKind` 加 `TASK_START`/`TASK_END`；render 支持新 kind |
| 文档 | SPEC 注入面（三个 runtime）、DATAFLOW |

## 六、分期

1. **P1 骨架**：task 子图最小闭环（begin→机械循环→end）+ 交界 + `steps_used` 对账 +
   trace 三件套；策略口先用小快模型占位。真机验证对账与闸门。
2. **P2 策略口**：JEV/小快模型正式接入 act_key；按 kind 的 provider 路由表生效。
3. **P3 MC 回填**：TaskOutput.reward 接机制三；语义步成为归账单元。
4. **P4 skill 种子**：完成任务路径落成 skill library 候选（机制二）。

## 七、风险与已知坑

- **F10 ×3**：第三张子图的 `context_schema` 声明同样不被校验；漏改签名的症状是
  运行期 `AttributeError`。grep 纪律 + 测试兜底（同 180 的做法）。
- **步数语义漂移**：episode 的 `step` 从"一键一步"变成"普通步一键、task 步一组键"。
  step memory / judge / stall 检测对 step 的假设要逐个核（P1 内完成）。
- **轻感知是新组件**：task 内圈的感知口径（判"对话框开了没有"这类）需要新实现，
  是 P1 里最大的未知工作量。

## 八、待拍板

1. **命名冲突**：现有 brain 域 `Task`（`task.py`，"episode 的边界就是任务的边界"，
   粗粒度 episode 级）与新 task 子图单元撞名。两个选项：(a) 现有 `Task` 改名
   （`Mission` 之类，动 brain 接口域）；(b) 新单元另起名。**必须二选一，不能共用。**
2. **双计数策略**：task 内按键是否同时消耗自己的 max_steps 和 episode 的 max_steps
   （本方案：是——episode 预算是世界交互总预算，task 预算是其内的分段闸门）。
3. **v1 策略口用什么**：JEV（若有现成 policy）还是小快模型路由（无训练、纯延迟优化）。
