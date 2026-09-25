"""`TaskRuntime`——**task 层的 context**（task 图 + 图外入口共用的那一个对象）。

## 它为什么存在

三层同构（run=规划器 / episode=拆解器 / task=执行器）的执行层 context。task 层
节点**只经注入到这里的 tool 访问外界**，判据与 run/episode 两侧同一条：
**节点需要它、但它跨不过 JSON 边界** → 进这里。

## 谁创建它、生命周期（F11）

`build.py`（唯一装配点）造一次，嵌在 `EpisodeRuntime.task` 里——task 图的
`context=…` 由 episode 侧的 `act` 格显式传（形态 B，同 run→episode 的模式）。
**一次 run 一份、跨局复用**，与外层两个 runtime 同生同死。

## 共享与独占

`game` / `trace` / `memory` / `reflector` 是**同一实例**的引用（装配时复制）——
按键借 episode 持有的世界端口，ActMemory 落同一个记忆库。`chooser` 是 **task 层
自己的 BrainTool 上的那个**（按需实例化，185：接 JEV / 小快模型时只换这一份）。

**帧槽住这里**（0923 188 下沉）：`frame_before` / `frame_after` 是按键链的
账（每键读写），键级执行在本层——槽跟着链走，episode 侧不再持有。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pokemon_agent.tools.interface import (
    ChoosePort,
    GameToolPort,
    JudgePort,
    MemoryToolPort,
    ReflectPort,
    TaskSummarizePort,
    TraceToolPort,
    VerifyPort,
)

if TYPE_CHECKING:
    from ..checkpoint import Checkpointer


@dataclass
class TaskRuntime:
    """task 层的 context。节点读法只有一条路径：`runtime.context.<字段>`。"""

    # ---- 依赖：外面递进来的 ----

    game: GameToolPort
    """世界（模拟器）端口：act 按键与轻感知全走它。**借 episode 持有的实例**
    ——世界只有一个，task 层不复制对象。"""
    chooser: ChoosePort
    """决策口（`plan_task` 每键问一次，出单键；受限 space）。**独立实例**——接
    JEV / 小快模型时在 `build.py` 换这一个对象即可，节点与类型零改动。194 起
    本口是真决策（链预填已删）。"""
    judger: JudgePort
    """判定口（`review_and_judge` 问"task 目标达成没有"；194 起本层有自己的
    判定）。**独立实例**——与 episode 层那个互不相干（185）。"""
    memory: MemoryToolPort
    """记忆库端口：ActMemory 落库与检索（与 `EpisodeRuntime.memory` 是
    **同一实例**）。"""
    reflector: ReflectPort
    """反思口（ActMemory 组装，**不调模型**）。"""
    verifier: VerifyPort
    """校验口（`task_done` 筛 ActMemory 用；与 episode 层各自的 BrainTool 上
    那个**互不相干**——按需实例化，185）。"""
    task_summarizer: TaskSummarizePort
    """task 蒸馏口（`task_done` 产 TaskMemory 用）。"""
    trace: TraceToolPort
    """记账（与 `EpisodeRuntime.trace` 是**同一实例**）。"""

    # ---- 账：跨 task 要活着的可变账 ----

    frame_before: tuple[str, int, str] | None = None
    """**这一步**开局画面的 `(episode_id, step, base64 PNG)`——帧槽的 `before` 位。

    写入口唯一：`frames.remember_frame()`（产出方：task perceive 格的 `sense`）。唯一读者是
    `store_step_episode_memory` 的 `before_frame`。"""
    frame_after: tuple[str, int, str] | None = None
    """**下一步**开局画面的 `(episode_id, step, base64 PNG)`——帧槽的 `after` 位。

    写新帧时旧的 `after` 挪进 `before`（"为什么恰好两步"、跨局清空，都在
    `frames.remember_frame` 的 docstring 里）。唯一读者是 `after_frame`。"""

    # ---- 存档：task 开局的世界快照由 `task_entry.begin_task` 调用 ----

    checkpointer: Checkpointer | None = None
    """存档器（`build.py` 造，三层 runtime 持有**同一实例**）；None = 不存档（测试或开关关闭）。"""


__all__ = ["TaskRuntime"]
