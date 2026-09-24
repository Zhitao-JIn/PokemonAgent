"""`EpisodeRuntime`——**episode 侧的 context**（episode 图 + 图外入口共用的那一个对象）。

## 它为什么存在

重构把节点从"类方法"变成"自由函数"之后，`self` 这条通道没了。runtime 就是
**`self` 减去 state 之后剩下的那一半**：外部递进来的依赖（Port / 能力对象）、
跨步要活着的可变账（帧槽）。

判据（一句话）：**节点需要它、但它跨不过 JSON 边界** → 进这里；
**能 JSON 化且图上要读** → 进 state。

## 谁创建它

`build.py`（唯一装配点）造一次，**一次 run 一份**，嵌在 `RunRuntime.episode` 里
由 run 侧的 `act` 格（`run/act/episode.py`）递下来——episode 图没有自己的外部调用面，
这是它拿到 context 的唯一路径。

## F10 的真相（与 run 侧共用）

langgraph 1.2.11 实测：**子图自己的 `context_schema` 声明不被校验**——父图传什么对象，
子图节点就拿到什么对象。这里声明 `EpisodeRuntime`、节点签名写 `Runtime[EpisodeRuntime]`
是**给人和脚本看的契约**，框架不替你查。漏改签名的症状高度一致：运行期在
`runtime.context.<字段>` 处炸 `AttributeError`，全在 episode 第一个读字段的节点上。

## 生命周期（F11）

context 在**整个 invoke 期间是同一个对象**（跨循环轮次不重建，外部引用看得见改动）
——所以可变账（帧槽）放它里面保得住。但**框架不重建它**：**一次 run 新建一份**、
跨局复用（帧槽的跨局清空由 `remember_frame` 自己兜），与这次 run 同生同死
（`run_id` 已归 `RunState`，186）。跨 run 复用同一个实例会让第二次 run 带着上一次的帧残留——**表现是
"图能跑、只是帧对不上"**，又一个不炸的错。

## 历史

0912 前它是 `EpisodeHarness` 的宿主字段；步 2/3 重构变成单一 `HarnessDeps`
（run/episode 两图共用）。2026-09-22 第 180 条拆成两个 runtime：episode 独占的
`game` / `brain_tool` / 帧槽归这里，run 级的 `planner` 归 `RunRuntime`——
episode 节点从此**看不见** planner（原来只是"不读"，现在是"结构上不在"）。
同日第 181 条按三层同构（run=规划器 / episode=拆解器 / task=执行器）把
`task: TaskRuntime` 嵌套进来——容器先行，task 图与节点随后
（`docs/PLAN_task_subgraph.md`）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.tools.interface import (
    DecomposePort,
    GameToolPort,
    JudgePort,
    MemoryToolPort,
    SummarizePort,
    TraceToolPort,
    VerifyPort,
)

from ..interface.reviewer import Reviewer
from ..task.task_runtime import TaskRuntime


@dataclass
class EpisodeRuntime:
    """episode 侧的 context。字段按带分节，**类型不重复**（一个对象一个字段）。

    节点读法只有一条路径：`runtime.context.<字段>`。
    """

    # ---- 依赖：外面递进来的，整 run 不变 ----

    game: GameToolPort
    """世界（模拟器）端口：动作空间、按键、感知、reset 全走它。**episode 独占**
    ——run 侧只有 `new_run` 的世界起点载入经 `run_rt.episode.game` 穿透。"""
    memory: MemoryToolPort
    """情景记忆 + 语义记忆（object）都走这一个端口（与 `RunRuntime.memory`
    是**同一实例**，两边存引用）。"""
    decomposer: DecomposePort
    """拆解口：`plan_episode` 在任务链空时问一次，把本局目标拆成任务链。"""
    judger: JudgePort
    """判定口（`review_and_judge` 问"本局目标达成没有"）。"""
    verifier: VerifyPort
    """校验口（`episode_done` 给 TaskMemory 打正/负标）。"""
    summarizer: SummarizePort
    """蒸馏口（`episode_done` 产 EpisodeMemory 与 reason）。"""
    trace: TraceToolPort
    """记账 req 由 harness 组装，payload 渲染与落盘都在 tool 层（与 `RunRuntime.trace`
    是**同一实例**）。"""
    reviewer: Reviewer
    """人与图之间的门（插话 + 审）——episode 侧只有 plan_episode / review_and_judge 读它
    （与 `RunRuntime.reviewer` 是**同一实例**）。没接控制台时是 `NullReviewer`。"""

    # ---- 嵌套：task 层的 context 由 episode 持有、将来经分流格递下去 ----

    task: TaskRuntime
    """task 层的 runtime（`build.py` 先造它、再造本对象）。**必传、恒非空**——
    task 图的 `context=…` 由本层 `act` 格显式传（形态 B，同本对象被 run 侧
    递下来的模式）。帧槽随 188 下沉到这里，`act` 派发时经它递入 task 图。"""

    # ---- 账：跨 task 要活着的可变账（episode 独占） ----

    # （帧槽已随 0923 188 下沉 `TaskRuntime`——键级执行在 task 层，槽跟着链走。）

    # episode 层自己取的帧（完整档）不进帧槽，`sense_frame` 账直接带图；槽只服务 task 层
    # ActMemory 的前后两张图（见 `task/frames.py`）。


__all__ = ["EpisodeRuntime"]
