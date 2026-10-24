# run goal 与可编辑目标表分离 —— intent

状态：已确认（2026-10-24，用户答复：检查点按建议拆分；样本步数上限改由 planner 的预算 + run 级预算兜底；ROADMAP 占位放 E 类）。

## 一句话意图

让 run goal 成为调用方显式传入、run 内不可变的独立对象，plan 初始为空、由 run planner 自己建执行目标；评分按“本 run、本执行线”取证据，不再按目标 id 找局。

## 为什么做（证据）

- 评测样本 `knowledge_shop_interaction`（要求与两位不同 NPC 对话）的 run 实际成功：run 级判定员以 `goal_done` 收尾，2/2 局完成。
- 机械评分却返回 N（unjudgeable）：`evals/agent_short_goal_run/scorer/registry.py:45` 用 `stream.episodes_for(sample.sample_id)` 做闸门，`stream.py:158-164` 只精确匹配 `episode_start.goal_id`。planner 把原条目标为 abandoned 并新建 `plan-<run_id>-1/-2`，原样本 id 下没有局，判据没有运行。
- 根因是建模：`pokemon_agent/harness/run/run_entry.py:114-119` 把同一个 `list[Task]` 既拼成 `run_goal`（`default_run_goal`，第 68-73 行），又包成 plan 第 0 行（`initial_plan`，第 60-65 行）。评测入口 `one.py:70` 没传 `run_goal`，`one.py:88` 又把 `task_id` 设成样本 id。
- run goal 本身没被改动：`plan_run` 的返回值（`plan_run.py:311-317`）不含它，`review_and_judge` 也不写它；`abandoned` 只改 plan 条目的 `status` 与 `note`（`planning.py:34-37`）。
- 数据集 140 条样本 `granularity` 全是 `run`，凡 planner 合法拆解都会触发同一问题。

## 做什么

1. 评分取证据：run 粒度样本取本执行线全部局，不依赖目标 id（`scorer/stream.py`、`registry.py`、`rules/shop.py` 三处、`utils.py`）。
2. `run_goal` 由调用方显式传入，评测入口不再依赖 `default_run_goal` 从任务文字拼。
3. 初始 plan 允许为空，去掉对 `goals` 非空的假设（`run_entry.py:109`、`begin/__init__.py:26`、世界 reset `run_entry.py:132`、恢复路径 `checkpoint/restore.py:114`）。
4. `docs/ROADMAP.md` 加占位条目：run 结束后的 run 级规划器。

## 不做什么

- 不新增 `RunState` 字段，不改 checkpoint 状态结构（`state_schema_hash` 不变）。
- 不加目标血缘字段（eval 内 `run_id` 已是可靠归属键）。
- 不实现 run 级规划器，不做 run goal 表与状态。
- 不改 `review_and_judge` 的停机逻辑，不改 `run_plan` 的 prompt，不用 prompt 禁止合法拆解。
- 不改 episode / task 粒度样本的取局语义。

## 目标层级（背景）

run goal 表（跨 run，未来）→ 当前 run goal（run 内不可变）→ plan（run planner 维护的执行目标）→ episode。一次 run 结束后重新规划下一个 run goal 是未来的 run 级规划器的职责，格式与 plan 同形、读 run 级结果；本任务只占位。

## 影响面

评分器（`evals/agent_short_goal_run/scorer`）、run 入口与恢复路径（`harness/run`、`harness/checkpoint`）、评测入口（`one.py`）、`run_start` 账的 `run_goals` 变空列表时的渲染与读侧、ROADMAP。

## 风险

- 世界 reset 的来源与样本步数上限是设计判断，只读过代码，没有探针验证；spec 的“已知未核实”列出，执行方遇偏差即停。
- `sample.max_steps` 不再约束第一局的 task 数，改由 planner 给的 `budget.limit` 与配置的 run 级预算（`max_episodes`、`plan_max_new_goals`、`max_planning_rounds`）兜底，评测的单样本成本分布可能变化。

## 成功的样子

- 对 `knowledge_shop_interaction` 同样形态的账（原条目从未有局、两局挂在新 id 下），机械评分进入判据，不再是 N。
- 以空 plan 启动的 harness 能由 planner 建目标并跑完。
- 全量 pytest、`ruff check`、`ruff format --check` 全绿，`state_schema_hash` 不变。
