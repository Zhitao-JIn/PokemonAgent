"""`RunHarness`：一个 run 的**外部调用面**——薄类，只装轮子不做决定。

## 它为什么还留着（D1 的落地形态）

`EpisodeHarness` 在步 3 消失了（没有外部调用面：只被 `RunHarness` 用），而
`RunHarness` 留着——**它有外部调用面**：实验核对脚本持有 `harness` 并调 `run()` /
`read_events()`；将来重建前端暴露层时还会接上"读目标表"这类只读接口。
这些是"长命对象 + 跨请求活着"的职责，不是图节点的职责：
节点是纯函数（`(state, runtime) -> dict`），而调用方需要一个**跨请求活着**的句柄。

## 它里面只有三件事

1. `__init__`：收下 `RunRuntime`（**run 侧的 context**，内嵌 `EpisodeRuntime`，D3/F10）、
   编译一次图；
2. 图外入口的转调：`run()` → `run_entry.new_run`
   （**图外的开局编排在那个函数里**，本类一行逻辑都不加）；
3. 一个薄委托给 `deps.trace`：`read_events`——读**磁盘账本**
   （0913 晚起唯一真相；本层仍然不认识 `pokemon_agent.trace`，只认识
   tool 层的 `TraceToolPort`）；
4. `_compile()`：把"图长什么样"交给 `run/run_graph.py`。

**0914 控制台改造删掉了六个对 `interaction` 的薄委托**
（`latest_goals` / `submit_human_note` / `submit_edit` / `pending_review` /
`review_deadline` / `submit_review_response`）：那套是"前端在另一个线程里
异步读写槽"的形状，控制台里人就在图的调用栈上，这些入口没有对应物了。
人怎么表态，看 `harness/console_reviewer.py`；目标怎么来，看
`run/plan_run/plan_run.py`（`planner.plan` + 插话循环）。

**依赖只有一个入口：`runtime`**（步 4 收口；180 起是 `RunRuntime`）：原先构造参数里那些
`trace` / `planner` / `judger` / `reviewer`，全都已经是 runtime 的字段
——再收一遍就有两份真源，而"两边指的不是同一个对象"这类错**不报错**。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import Goal, Task
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.schemas.harness.domain import EpisodeOutput

from .run_entry import new_run
from .run_graph import compile_run_graph
from .runtime import RunRuntime


class RunHarness:
    """run 级图的**外部调用面**：完整一局游戏（run_id），目标表驱动，episode 为子图。

    （原 `HarnessPort` 那张 Protocol 的落地形态——Port 本身已在步 4 删除，D5：
    实现方就在隔壁文件，"港口"的定义却是"实现方在系统之外"。）
    """

    def __init__(self, deps: RunRuntime) -> None:
        """前置条件：`deps` 非空（装配点在 `build.py`，那里也是唯一的 new 处）。

        `deps.reviewer` / `deps.planner` / `deps.judger` **必须由装配处给全**（`build.py` 的缺省
        是 `NullReviewer` / `BrainTool.build(...)`）——本类不再兜底新建：那些对象要
        **跨节点共享同一份策略**（`plan` 与 `review` 都得是同一个 `reviewer`），
        本类兜底建出来的那个不会是节点手里那份，两边就断开了，而表现只是
        "人看不到东西、图却照跑"。缺了就在构造时就炸，别等跑到一半。
        """
        assert deps is not None, "RunHarness needs the shared RunRuntime"
        assert deps.reviewer is not None, "RunRuntime.reviewer 必须由装配处给全"
        assert deps.planner is not None, "RunRuntime.planner 必须由装配处给全"
        assert deps.judger is not None, "RunRuntime.judger 必须由装配处给全"
        self.deps = deps
        self._graph = self._compile()

    # ---- 入口（图外编排在 run_entry）----

    def run(
        self, run_id: str, goals: list[Task], run_goal: Goal | None = None
    ) -> tuple[list[EpisodeOutput], int, int, float]:
        """跑完一个 run，返回 run 级结算 `(outcomes, total, succeeded, success_rate)`。

        编排（RUN_START → 进图 → 取结算/RUN_END，异常补 RUN_ERROR）在
        `run_entry.new_run`——本方法只是一道**外部调用面**。

        `goals` 是初始目标表（`list[Task]`）；run 内部把每条包成 `GoalEntry`
        （`run_entry.initial_plan`），调用方不必认识那张表。
        `run_goal` 不给时由目标表文字拼一个（`run_entry.default_run_goal`）。
        """
        return new_run(self.deps, self._graph, run_id=run_id, goals=goals, run_goal=run_goal)

    # ---- 读账（薄委托给 deps.trace）----

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        """读**磁盘账本**——0913 晚起事件流的唯一真相。

        `meta` 给了就只返回**每个键都相等**的那批（`TraceToolPort.read_events`
        的交集筛选）：整 run 用 `{"run_id": <RunState.run_id>}`（186 起 id 归 state），某一局再加上
        `episode_id`。**薄委托**：本层不认识 `pokemon_agent.trace`，只认识
        tool 层的 `TraceToolPort`。

        后置条件：按 `(ts, uuid)` 升序；无匹配时返回空列表（不抛）。
        """
        return self.deps.trace.read_events(meta)

    # ---- 图组装 ----

    def _compile(self) -> CompiledStateGraph:
        """把"图长什么样"交给 `run/run_graph.py`——本方法只留一句转调。

        拓扑全在 `run/run_graph.py`。
        """
        return compile_run_graph()


__all__ = ["RunHarness"]
