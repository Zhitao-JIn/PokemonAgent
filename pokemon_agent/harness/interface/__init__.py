"""harness/interface 包统一出口：harness 层**真端口**——`Planner` 与 `Reviewer`。

**判据：港口 = 实现方在系统之外**。这里曾经住着
两张"镜子"——`HarnessPort`/`EpisodeHarnessPort`，实现方就是隔壁文件的
`RunHarness`/`EpisodeHarness`；D5 已删（步 4：653 行零信息量的抄本，20 个方法全是
`...`，而"图有哪些节点"由 `episode_graph.py` 的 `add_node` 说、"节点改哪一处"由那张
逐节点的职责表说，都**可执行/可核对**）。同一次收口里搬走的还有：

- `RunState` → `run/run_state.py`（状态不是能力）；
- `EpisodeRunState` → `episode/episode_state.py`；
- 策略常量（`PLAN_MAX_NEW_GOALS`/`BRAIN_MAX_ATTEMPTS`…）→ 顶层
  `pokemon_agent/config.py`（它们与其余策略常量同族，集中一处才好调实验参数）；
  包出口**不再**导出常量——需要的人直接 `from pokemon_agent.config import X`。

一句话：`interface/` 从此只回答"harness 需要外面给什么"，不再回答"harness 自己长
什么样"。

**0914 控制台改造后这里只剩两个真端口**：`Planner`（plan 位置的 input 来源）与
`Reviewer`（人与图之间的门——插话 + 审）。旧的 `HumanReviewer` / `HumanDecision`
随槽机制一起删除：那套是"前端在另一个线程里异步回话"的形状，而控制台里
**人就在图的调用栈上**，两种机制的返回值都不一样了。

**0914 S2 给 `Planner` 补上了产出模型**：`PlannerOutcome`（新增 + 定点更新 + 收手
判定）与 `GoalUpdate`。它们住这一层而不是 `schemas/`——产出是 run 级**编排**词汇
（`GoalEntry` 的状态迁移），不是跨层的通用数据形状。

**没有懒加载**：这两个 Protocol 都零依赖（只 import `schemas` 与同包的
`planner_context`/`planner_outcome`），不会和 `schemas.harness` 形成初始化循环——
旧的那套 `__getattr__` 机制随 `HumanReviewer` 一起删掉了。
"""

from __future__ import annotations

from .planner import Planner
from .planner_context import PlannerContext
from .planner_outcome import ALLOWED_UPDATE_STATUSES, GoalUpdate, PlannerOutcome
from .reviewer import Reviewer

__all__ = [
    "ALLOWED_UPDATE_STATUSES",
    "GoalUpdate",
    "Planner",
    "PlannerContext",
    "PlannerOutcome",
    "Reviewer",
]
