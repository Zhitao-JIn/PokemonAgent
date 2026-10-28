# intent —— 短期样本的冻结版（冻结 plan·L1）

> 流程位置：**intent.md**（待确认）→ spec → plan → 落码
> 关联：`docs/eval_freeze/intent.md`（冻结机制）、`docs/eval/mid_tasks/intent.md`（三档定义）、`evals/agent_short_goal_run/dataset/v20261021_merged_583/`（现有 20 条）
> 状态：待确认。依赖冻结机制先落地。

## 一、一句话意图

为现有 20 条短期样本各写一张固定的 task 表，建成新版本数据集：episode 内的 task 不再由 decomposer 临时拆，只考 choose 与 task 记忆。

## 二、为什么

1. 短期档要考的是同一 episode 内 choose 的决策与 task 记忆；plan·L1 自由时，decomposer 的随机拆法会混进成败，失败时分不清是拆错还是选错。已有例子：`door_transition` 的失败里 agent 在同一行反复横移，`shop_interaction` 首位店员售罄就结束，都是规划层的范围与放弃判断问题。
2. 现有 20 条都是单 episode，档位上本来就属于短期，只差冻结 plan·L1。

## 三、做什么

1. 新建数据集版本目录，冻结后不改；起点 `.state`、机械判据、红线、`success_criteria` 与现版一致，只新增 `tier="short"` 与 `goals`（恰好一条）及其 `tasks`。
2. task 表的写法：每个 task 写动作级完成信号（边界要素 B2）和停手（B3），与对应的机械判据一一对应；不写路径、不写坐标。
3. 按类别给 task 数的范围：

| 类别 | 条数 | task 数 | 拆法 |
|---|---|---|---|
| battle | 7 | 1 | 目标本身就是一个菜单操作或一次动作 |
| catch | 2 | 1 | 一次削弱或一次投球 |
| center | 2 | 1–2 | 进中心可单独一个 task，治疗另一个 |
| dialog | 2 | 1 | 一段对话 |
| movement | 2 | 1 | 一次到达 |
| shop | 5 | 1–2 | 对话两位不同 NPC 拆成两个 task，每个 task 一位；购买类按"打开列表 / 选择确认"拆 |

4. 样本用冻结机制的短期档（`tier="short"`）加载；每个样本同时保留空 task 表的对照设置，用来量化 decomposer 带来的差异。

## 四、不做

- 不改机械判据、红线与现有数据集版本；不新增样本；不冻结 plan·L2（choose）。
- 不为凑 task 数把单步目标硬拆成多步。

## 五、已定与待定

- 20 条全部转成冻结版：单步样本的 task 表只有一条，作用是去掉 decomposer 把一个动作拆成多个 task 的可能。
- 待定：数据集版本目录命名（沿用 `v20261021_` 前缀的日期规则，还是单独起名）。

## 六、影响面与风险

- 影响面：新数据集目录、`loader.py` 的版本登记、对应测试；不碰生产代码。
- 风险：task 表写得太细会把 choose 的决策空间压缩掉，变成只测按键执行；每条 task 只写完成信号与停手，不写做法。

## 七、成功的样子

- 20 条冻结版样本全部通过加载校验与起点预检。
- 同一样本在冻结与空 task 表两种设置下都能用同一判据评分，可以比较两者的成功率与步数。
