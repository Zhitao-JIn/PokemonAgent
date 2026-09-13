"""`episode`：**派发这一局**——run 图里那格"接上 episode 子图"的地方（步 2 / D1-①）。

派发由 `episode/episode_entry.py` 的图外入口编排（开局的 reset + 首帧感知在图外
——为什么必须如此见该文件的模块文档）：

- 普通派发 → `episode_entry.run_new`（EPISODE_START → `begin_episode` → 进图 → 取结算）。

返回的状态增量就是**父子交界那张键表的回程**（D2）：`outcome` 交给 `reflect`。
`task`/`episode_goals` 已在 `dispatch` 里写过，这里不重复写（F1 的反作用：
子图不输出的键，父侧保持旧值——所以也不需要"清空"它们）。

**恢复分支已删**（见 `CHANGELOG.md` 2026-09-13 第 57 条）：原先这里还有一条
`resume_episode` 非空 → `episode_entry.run_resume` 的路径，随 checkpoint 恢复链
一起删掉了。

**异常不在这里兜**：异常会一路冒穿到 `invoke()` 的调用方（F3），兜底是挂在同一格上的
`dispatch.episode_error_handler`（F4）。

## 子图为什么是"懒取的模块全局"

节点签名 `(state, runtime) -> dict` 里没有地方递一张**编译好的图**——而它是**图的产物**，
不是依赖（D3 只把 `HarnessDeps` 塞进 `Runtime`：一个**全图唯一**的对象，塞一张图进去会
让"依赖从哪来"多出第二个答案）。所以子图挂在模块全局上、首次用到时编译一次：

- 不在 import 期编译：`check_imports.py` 会 import 每个模块，import 期建图是白费的副作用；
- 不每次调用都编译：那一格每派发一局跑一次，重编译纯属浪费。

`_EPISODE_GRAPH` 是**缓存**，不是第二份真源——它由 `compile_episode_graph()` 产出，
和 `check_graph_phases.py` 核的那张图逐字同一份。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from ...deps import HarnessDeps
from ...episode import compile_episode_graph, episode_entry
from ..run_state import RunState

_episode_graph: CompiledStateGraph | None = None


def episode_graph() -> CompiledStateGraph:
    """episode 子图：**编译一次、缓存**（每派发一局只 `invoke`、不重编译）。

    惰性编译的理由见本文件模块文档（import 期不建图、调用期不重建）。
    """
    global _episode_graph
    if _episode_graph is None:
        _episode_graph = compile_episode_graph()
    return _episode_graph


def episode(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """跑完这一局：把图外入口的结算取回来。

    前置条件：`state.episode_id` 非空、`state.task` 非空（都是 `dispatch` 写的）。

    后置条件：trace 里恰好多一条 EPISODE_START 与一条 EPISODE_END（图外入口的契约）；
    返回 `{outcome}`——它是 `reflect` 的唯一输入。
    """
    deps = runtime.context
    assert state.episode_id, "episode() without an episode_id"
    assert state.task is not None, "episode() without a task"
    graph = episode_graph()

    outcome = episode_entry.run_new(
        deps,
        graph,
        episode_id=state.episode_id,
        task=state.task,
        stack=state.goals,
    )
    return {"outcome": outcome}


__all__ = ["episode", "episode_graph"]
