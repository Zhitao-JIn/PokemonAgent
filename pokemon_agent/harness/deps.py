"""`HarnessDeps`——**全图唯一的 context**（run 图与 episode 图共用的那一个对象）。

## 它为什么存在

重构把节点从"类方法"变成"自由函数"之后，`self` 这条通道没了。`HarnessDeps` 就是
**`self` 减去 state 之后剩下的那一半**：外部递进来的依赖（Port / 策略对象）、
构造时定下的开关、整 run 的记号、跨 episode 要活着的可变账。

判据（一句话）：**节点需要它、但它跨不过 JSON 边界** → 进这里；
**能 JSON 化且图上要读** → 进 state。

## 为什么只能有一个（F10）

langgraph 1.2.11 实测：**子图自己的 `context_schema` 声明不被校验**——父图传什么对象，
子图节点就拿到什么对象。声明成不同类型**不报错**，子图节点会**静默**读到不存在的属性。
所以全图只能有一个 context 类型：`HarnessDeps`。写 `Runtime[...]` 时类型参数只能填它
（`scripts/check_graph_phases.py` 有机械核对）。

## 生命周期：一次 run 新建一份（F11 的代价）

context 在**整个 invoke 期间是同一个对象**（跨子图、跨循环轮次都不重建，外部引用看得见
改动）——所以可变账（帧表）放它里面保得住。但**框架不重建它**，生命周期得由调用方规定：
**一次 run 新建一个**，与这次 run 的 `run_id` 同生同死。跨 run 复用同一个实例会让第二次
run 带着上一次的帧账残留（`pending_frames` 里塞着已经不存在的 episode 的 PNG），
而**表现是"图能跑、只是帧对不上"**——又一个不炸的错。

## 字段四带

| 带 | 字段 | 何时定 |
|---|---|---|
| **依赖** | 5 根 Port + 2 个策略对象 + `checkpoint_root` | 装配时注入，整 run 不变 |
| **开关** | `auto_push_goals` / `auto_decide_done` | 构造时定，`plan` 读它决定"模型能否自主改栈" |
| **记号** | `run_id` / `world_reset_done` | 整 run 的 |
| **账** | `frame_event_ids` / `pending_frames` | 键带 `episode_id`，累积 |

（步 5b 之前是 6 根：多出来那根 `checkpoint` 已随 `tools/checkpoint_tool.py` 的解散
销账——`checkpoint_root` 只是「一条路径」，不是一根 Port。）

**步 2 落地了什么**：`EpisodeHarness` 在构造时建出（或收下）一份 `HarnessDeps`，
`self.deps`，并把原先的宿主字段**指向它**——`_frame_event_ids` / `_pending_frames`
与 `deps` 的同名表是**同一个 dict 对象**（一份真源、两个句柄），`_run_id` /
`_run_state_dump` / `_world_reset_done` 变成读 `deps` 的同名项（前者是 `property`）。
`episode/entry.py` 的四个装配器收的也是这份 `deps`——于是"图外侧门"与"节点"看到
的是同一个对象，不会出现两个真源。

**这两步都已落地（2026-09-12 注）**：

- ~~**步 3**~~：节点已搬成自由函数（签名 `(state, runtime: Runtime[HarnessDeps])`），
  依赖从 `runtime.context` 读，`self.deps` 这层别名已消掉。

**生命周期（F11 的代价）已收口（2026-09-12 注）**：`deps` 由 `build.py` 装配、
一次 run 一份（`RunHarness.__init__(deps)`），不再是随 `EpisodeHarness` 走的构建期
字段——那个类已删。跨 run 复用同一个实例仍会带着上一次的帧账残留，这条约束现在由
装配处保证。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pokemon_agent.tools.interface import (
    BrainToolPort,
    GameToolPort,
    MemoryToolPort,
    TraceToolPort,
)

from .interface.human_reviewer import HumanReviewer
from .run_data_center import RunDataCenter


@dataclass
class HarnessDeps:
    """全图唯一的 context。字段按"四带"分节，**类型不重复**（一个对象一个字段）。

    节点读法只有一条路径：`runtime.context.<字段>`。
    """

    # ---- 依赖：外面递进来的，整 run 不变 ----

    game: GameToolPort
    memory: MemoryToolPort
    """情景记忆 + 语义记忆（object）都走这一个端口。"""
    brain_tool: BrainToolPort
    trace: TraceToolPort
    """记账 req 由 harness 组装，payload 渲染与落盘都在 tool 层。"""
    reviewer: HumanReviewer
    """人类审查者（`AutoContinueReviewer` 是没接前端时的默认实现）。"""
    data_center: RunDataCenter | None = None
    """前后端交互的中间层（goals 槽 + review 槽 + human_note 槽）。`None` = 没接前端。"""

    # ---- 开关：构造时定，整 run 不变 ----

    auto_push_goals: bool = True
    """`False` 时 `plan` 丢弃模型的 `push_goals`（人工通道不受影响）。"""
    auto_decide_done: bool = True
    """`False` 时 `plan` 没有任何权力让 run 结束，栈空也路由去 `review` 问人。"""

    # ---- 记号：整 run 的 ----

    run_id: str = "local"
    """这次 run 的标识：拼截图路径、标 `EpisodeMemory.run_id`、给事件盖 `run_id`。"""
    world_reset_done: bool = False
    """世界起点存档读过了没有（`_begin` 是唯一读点）。

    **不落盘**，但**两处都要显式写**：`_begin`（首局 reset 后）与未来的恢复入口
    ——后者不能省：恢复路径不经过 `_begin`，而本局跑完后**下一局的 `_begin` 会读它**，
    少写一处的症状是"能恢复、能跑完本局，但下一局世界回退到 ROM 起点"
    （`PLAN_graph_composition.md` §5.2-8）。
    """

    # ---- 账：键里带 episode_id，整 run 累积（没有"每局要清"的东西） ----

    frame_event_ids: dict[tuple[str, int], int] = field(default_factory=dict)
    """`(episode_id, step) → 承载这一帧的事件的 event_id`——**登记表**。

    截图与 trace 事件共享 event_id（文件名 = `<event_id>.png`），而"这一帧挂在哪条
    事件上"并不固定（开局那帧挂 `OBSERVE`，之后每帧挂那一键自己的 `AFTER_ACTION`），
    所以"某一步的开局画面在哪个文件"不能由步号算出来，必须有这张对账表。
    """
    pending_frames: dict[tuple[str, int], str] = field(default_factory=dict)
    """`(episode_id, step) → 那一步开局画面的 base64 PNG`——**暂存表**。

    帧要从"产出它的那一格"传一手到"把它挂上事件的那一格"。唯一的例外是第 0 步
    ——那一帧由 `_begin` 产出，而 `_begin` 在图外、没有"自己那条账"可挂，于是先
    存进这里，等链首 `record_observation` 记 `OBSERVE` 时取走（`pop`）。所以它
    **只在第 0 步非空**。
    """


__all__ = ["HarnessDeps"]
