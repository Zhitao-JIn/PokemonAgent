"""`save_checkpoint`：**已停用的存档节点**——保留图上的位置与名字，内部空转。

## 为什么留着这一格而不拆掉

存档实现已整体删除（见 `CHANGELOG.md` 2026-09-13 第 57 条）。但这一格**留在图上**：

1. 它是 episode 图的**入口点**——拆掉要改入口点、`record_observation` 的入边、
   `close_step` 出口条件边三处，动的是图拓扑，风险集中在真机；
2. 它的位置语义（"链边界"）本来就有价值：链内执行是纯 RAM 确定的，从链首
   重放能逐帧复现。将来若重做存档，"哪一格是链边界"这个知识不必重新推导；
3. 它空转的代价是**每个链首多一个 superstep**（`NODES_PER_DECISION` 已经把
   它算进去了），量级可忽略。

## 后果：这张图不再能恢复进程

存档端（这里）与恢复链（`episode_entry.prepare_resume`/`void_timeline`、
`run_entry.resume_run`）是**成对删除**的。删完之后本仓**只有"新开一 run"一条
路径**，进程死掉就从头再来——`RunHarness.resume_run` 已不存在。

## 它曾经做什么（留档）

写 `EpisodeCheckpoint`（模拟器快照 + `EpisodeRunState` + run 级 dump + trace
游标 + 本局帧账），并补一条 `CHECKPOINT_SAVE` 接缝事件。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def save_checkpoint(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """**空转**：不写存档、不写账、不改任何 state 字段。

    前置条件：无（本节点不读 state 也不读 deps）。
    后置条件：返回空增量（本节点不改任何 state 字段）。

    保留 `(state, runtime)` 签名是为了跟同一张图上其余 20 个节点同形——
    `check_graph_phases.py` 按"节点名 = 实现文件名"核对，签名不同形会被它挑出来。
    """
    return {}
