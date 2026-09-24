"""`RunRuntime`——**run 侧的 context**（run 图 + 图外入口共用的那一个对象）。

## 它为什么存在

与 `EpisodeRuntime` 同一条判据：**节点需要它、但它跨不过 JSON 边界** → 进这里；
**能 JSON 化且图上要读** → 进 state。run 侧节点（plan / review / begin / dispatch /
episode 五格）读的是这份。

## 它持有 episode

`episode: EpisodeRuntime` 是**嵌套持有**——这是接线上的硬约束，不是偏好：
episode 图的 `context=…` 由 `episode_entry._invoke` 显式传（形态 B），episode 自己
没有任何地方能"拿到"第二份 context，只能由 run 侧递下去（run 图的 `act` 格）
那一格做 `episode_entry.run_episode(runtime.context.episode, …)`。

**brain 能力按层注入**（185）：run 侧只注入 `planner`（plan 链路），episode 侧
注入其余六个能力对象。`trace` / `memory` / `reviewer` 两边是**同一实例**（装配时
复制引用）——隔离的是类型可见性，不是运行期实例。**id 一律归 state**（186）：
`run_id` 住在 `RunState` 上，runtime 不再复制（trace 的归属章由
`TraceTool.build(run_id=…)` 构造期持有）。

## 生命周期（F11）

由 `build.py` 装配、**一次 run 一份**（`RunHarness.__init__(run_rt)`）。跨 run 复用
同一个实例会让第二次 run 带着上一次的帧残留（残留在 `run_rt.episode` 的帧槽里）。

## 历史

0912 前依赖分散在 `RunHarness` / `EpisodeHarness` 的实例字段上；步 2/3 重构收成
单一 `HarnessDeps`（两图共用一个对象）。2026-09-22 第 180 条拆成两个 runtime；
同日第 184 条撤销 `planner` 壳（它只是 `brain_tool.plan` 的包装）；第 185 条
能力对象化后，run 侧注入的是 tool 层的 `Planner` 对象（`PlanPort`）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.tools.interface import JudgePort, MemoryToolPort, PlanPort, TraceToolPort

from ..episode.episode_runtime import EpisodeRuntime
from ..interface.reviewer import Reviewer


@dataclass
class RunRuntime:
    """run 侧的 context。episode 经嵌套字段递下去。

    节点读法只有一条路径：`runtime.context.<字段>`（episode 侧东西一律经
    `runtime.context.episode.<字段>`）。
    """

    # ---- 依赖：外面递进来的，整 run 不变 ----

    trace: TraceToolPort
    """记账 req 由 harness 组装（与 `EpisodeRuntime.trace` 是**同一实例**）。"""
    memory: MemoryToolPort
    """plan / review 读记忆（与 `EpisodeRuntime.memory` 是**同一实例**）。"""
    reviewer: Reviewer
    """人与图之间的门：plan 位置的插话 + review 的审（与 `EpisodeRuntime.reviewer`
    是**同一实例**——"人对 plan 说的那句话"要能传到审那一格，必须同对象）。"""
    planner: PlanPort
    """run 层的规划口（`BrainTool.build(plan=…)` 组装的 `Planner`）——
    `plan_run` 格唯一使用者。原 `planner` 壳随 184 撤销、185 起注入的就是
    tool 层的能力对象本身。"""

    # ---- 嵌套：episode 侧的 context 由 run 持有、经 episode 节点递下去 ----

    judger: JudgePort
    """run 层判定口：`review_and_judge` 问"run_goal 达成没有"（素材是局摘要）。"""
    episode: EpisodeRuntime
    """episode 侧的 runtime（`build.py` 先造它、再造本对象）。**必传、恒非空**。"""


__all__ = ["RunRuntime"]
