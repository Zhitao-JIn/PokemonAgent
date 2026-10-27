# intent —— 评测时冻结规划层（短期冻结 plan·L1，中期冻结 plan·L0）

> 流程位置：**intent.md**（待确认）→ spec.md → plan.md → 落码
> 关联：`docs/eval/mid_tasks/intent.md`（三档任务）、`docs/run-goal-split/intent.md`（run goal 与目标表分离）、`docs/brain_scope/intent.md`（三级目标）
> 状态：已确认（2026-10-27，用户答复：冻结表不能被本层修改、下层可自由运行，冻结表任一条判负即样本失败；按此开工）。

## 一、一句话意图

让评测样本可以带上"已定好的规划"：中期样本冻结 plan·L0（episode 目标表），短期样本冻结 plan·L1（episode 内的 task 表），被冻结的那一层不再调用模型，下面各层照常自由运行。

## 二、为什么

1. 三档任务各考一层记忆与规划（短期：choose 与 task 记忆；中期：plan·L1、episode 索引；长期：plan·L0）。规划层不冻结，下层的成败会被上层随机拆法污染，且 episode 边界无法预先钉死，"跨 episode 证据"只能事后统计。
2. 现状：`new_run` 的 `goals` 参数可以带初始目标表，但每个 episode 结束后 `plan_run` 仍会调用 planner，可以重开、新增、放弃目标；`plan_episode` 每轮都会调用 decomposer，且 episode 入口没有任何地方能带 task 表。评测入口 `evals/agent_short_goal_run/solver/runner/one.py` 现在传空目标表，目标全由 planner 建。

## 三、做什么

1. 两个开关（配置，默认关）：`freeze_run_plan`、`freeze_episode_plan`。开启后对应的 plan 节点不调用模型、不写规划账、不问 reviewer，只按表序派发。**冻结的表不能被本层修改，下层可以自由运行**：冻结表里任何一条判负（`FAILED` / `ABANDONED`），本层直接以新的终止类别 `frozen_item_failed` 收尾并算失败，不重开、不重试、不继续派后面的条目；表全部跑完仍未判成功，机械收尾（复用 `planning_exhausted` / `decompositions_exhausted`）。
2. 目标表条目可以带冻结的 task 表（`GoalEntry.frozen_tasks`），经 `EpisodeInput.tasks` 带进 episode，作为 `plan_episode` 的初始 task 表。
3. 评测样本新增档位与冻结内容：`tier`（short / mid / long）、`goals`（可选，每条带目标、判据、预算，短期还带 `tasks`）；`one.py` 按档位传目标表与开关。长期档不冻结，只给 run goal，行为与现状一致。

## 四、不做

- 不改各层 judge 的判定本身；不改任何 prompt；不改现有 20 条样本与它们的判据。
- 不冻结 plan·L2（choose）；不做长期样本；不改机械判据。
- 不为冻结模式新增 reviewer 能力（冻结层不问 reviewer）。

## 五、已定

- `GoalEntry` 增字段、`Termination` 增 `frozen_item_failed` 会改变 `state_schema_hash`：接受；评测起点已是原始 `.state`，不受影响，checkpoint 相关测试需要同步时按 spec 停止条件处理。

## 六、影响面与风险

- 影响面：`settings`（两个开关）、`harness/run/plan_run`、`harness/run/act/dispatch.py`、`harness/episode/episode_entry.py`、`harness/episode/plan_episode`、`schemas/harness/domain`（`GoalEntry`、`EpisodeInput`）、评测样本契约与 `one.py`。
- 风险：读侧（评分器、reviewer、trace 回放）可能假设每轮都有 plan / decompose 账；冻结模式不写这些账，必须逐个核实读方（见 spec 停止条件）。

## 七、成功的样子

- 开关关闭时，全部现有测试与行为不变。
- 开关开启时：带目标表的 run，planner 零调用，episode 数与表序一致；带 task 表的 episode，decomposer 零调用，task 数与表序一致。
- 同一个中期样本在冻结与空表两种设置下都能用同一判据评分。
