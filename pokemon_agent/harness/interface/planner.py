"""`Planner`：**plan 位置的 input 来源**——给出一版规划（新增 + 定点更新 + 收手判定）。

**它解决什么问题**：run 图 `plan` 那一格要的从来是"下一步做什么"。这件事
一开始由人来做（控制台），后来**加了模型实现**（`BrainPlanner`，
`docs/PLAN_planner_v2.md` 的渐进披露 + 状态化任务表）：

| 实现 | 什么时候用 |
|---|---|
| `BrainPlanner` | **默认**：模型读记忆索引 + 详情 + 目标表，自主规划（`build.py` 的缺省装配） |
| `ConsolePlanner` | 人手驾驶：人在控制台上一个目标一行地写（`common.CONTROL_SETUP_HINT`） |
| `NullPlanner` | 无头、且**要显式关掉规划**：不新增、不表态 |

> **`NullPlanner` 必须显式传**：`planner=None` 装配的是 `BrainPlanner`（见 `build.py`）。
> 它还有一个用法是"**只要读口、不要决策**"：配 `auto_push_goals=True` 时 `plan`
> 仍会走一遍 `_context()`（读记忆、排执行序、预取详情）再把空产出交给表末检
> ——`check_harness.py` 靠这一手让 S2 的读侧在真机上被走到。

把"来源"抽成一个 Protocol，换来源时**只换实现**——`run` 图、目标表、
插话机制、`review` 节点全都不动。

**它和"插话"是两件事**（用户 0914 明确纠正过一次）：

- `Planner` = **给出一版**（产出新目标与定点更新）；
- 插话（`Reviewer.inject`）= **对这一版表态**（说一句"不对"）。

**为什么它是 harness 的协议而不是 brain 的**：`Planner` 的产出
（`PlannerOutcome`：带 status / parent_id 的 `GoalEntry`）是 run 级**编排**词汇，
不是 brain 的领域模型。brain 那边对应的是 `Brain.plan()`——它的产出是 `RunPlan`
（纯任务，无状态），由 `BrainPlanner` 转成 `PlannerOutcome`。
**这正是铁律 2 的形状**：协议归属看谁消费，run 图消费的是 `GoalEntry`，所以协议住 harness。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .planner_context import PlannerContext
from .planner_outcome import PlannerOutcome


@runtime_checkable
class Planner(Protocol):
    """plan 位置的 input 来源：看目标表与历史，给出一版规划。"""

    def plan(self, ctx: PlannerContext) -> PlannerOutcome:
        """给出一版规划：要新增什么目标、要改哪些已有条目的状态、该不该收手。

        ctx：规划素材——当前目标表、本 run 的局索引与少量详情、地图交互事实
            （`PlannerContext`；0914 S2 之前这里装的是全量事件流）。
        后置条件：返回**未落表**的产出——`entries` 是待追加的新条目（调用方负责
            append 进 `RunState.plan`）、`updates` 是对已有条目的定点表态
            （只允许 `PENDING` / `ABANDONED`，见 `ALLOWED_UPDATE_STATUSES`）。
            三者都空 = "我没有意见"（这时由表末检决定要不要 done）。
        失败契约：实现方出错时**抛异常**，不要返回空产出——空产出是"我没有意见"
            这个**正常结论**，两者必须分得开（否则"规划器坏了"会伪装成"没有新目标"，
            再被表末检翻译成"目标做完了"）。
        """
        ...


__all__ = ["Planner"]
