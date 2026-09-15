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
——这条纪律**曾经**由 `scripts/check_graph_phases.py` 机械核对，**那个脚本已经不在仓库
里**（见 `docs/spec/harness/SPEC.md` 的已知缺口），现在只靠人眼。

## 生命周期：一次 run 新建一份（F11 的代价）

context 在**整个 invoke 期间是同一个对象**（跨子图、跨循环轮次都不重建，外部引用看得见
改动）——所以可变账（帧槽）放它里面保得住。但**框架不重建它**，生命周期得由调用方规定：
**一次 run 新建一个**，与这次 run 的 `run_id` 同生同死。跨 run 复用同一个实例会让第二次
run 带着上一次的帧残留（`frame_before`/`frame_after` 里塞着不存在的 episode 的帧），
而**表现是"图能跑、只是帧对不上"**——又一个不炸的错。

## 字段四带

| 带 | 字段 | 何时定 |
|---|---|---|
| **依赖** | 4 根 Port + 2 个策略对象（`reviewer` / `planner`） | 装配时注入，整 run 不变 |
| **开关** | `auto_push_goals` / `auto_decide_done` | 构造时定，`plan` 读它决定"模型能否自主改表" |
| **记号** | `run_id` / `world_reset_done` | 整 run 的 |
| **账** | `frame_before` / `frame_after`（覆盖式） | 键里带 `episode_id` |

（步 5b 之前是 6 根：多出来那根 `checkpoint` 已随 `tools/checkpoint_tool.py` 的解散
销账——`checkpoint_root` 只是「一条路径」，不是一根 Port。）

**0914 封套改造：`frame_event_ids` 那张累积登记表已删。** 它的唯一用途是"帧槽未命中时
回盘找承载这一帧的事件"（`TracePort.read_event`），而事件不再自带 `frame_png` 之后那条
路整条没了——帧槽成了画面**唯一**的取用通道。于是"账"那一带只剩覆盖式两个位。

**0914 控制台改造：`interaction` 这根被替换成 `planner`。** 原来那个
`RunInteraction | None` 是"跨线程信箱"（goals / human_note / review 三组槽），
而控制台里人就在图的调用栈上——不需要信箱，需要的是**两个同步接口**：
`reviewer`（插话 + 审）与 `planner`（给出一版目标）。两者都恒非空
（无头时装配成 `NullReviewer` / `NullPlanner`），于是旧代码里那一串
`assert interaction is not None` 也一并消失。


**步 2 落地了什么**：`EpisodeHarness` 在构造时建出（或收下）一份 `HarnessDeps`，
`self.deps`，并把原先的宿主字段**指向它**——`_pending_frames`
（今 `frame_before` + `frame_after`）与 `deps` 的同名表是
**同一份对象**（一份真源、两个句柄），`_run_id` /
`_run_state_dump` / `_world_reset_done` 变成读 `deps` 的同名项（前者是 `property`）。
`episode/entry.py` 的四个装配器收的也是这份 `deps`——于是"图外侧门"与"节点"看到
的是同一个对象，不会出现两个真源。

**这两步都已落地（2026-09-12 注）**：

- ~~**步 3**~~：节点已搬成自由函数（签名 `(state, runtime: Runtime[HarnessDeps])`），
  依赖从 `runtime.context` 读，`self.deps` 这层别名已消掉。

**生命周期（F11 的代价）已收口（2026-09-12 注）**：`deps` 由 `build.py` 装配、
一次 run 一份（`RunHarness.__init__(deps)`），不再是随 `EpisodeHarness` 走的构建期
字段——那个类已删。跨 run 复用同一个实例仍会带着上一次的帧残留，这条约束现在由
装配处保证。
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.tools.interface import (
    BrainToolPort,
    GameToolPort,
    MemoryToolPort,
    TraceToolPort,
)

from .interface.planner import Planner
from .interface.reviewer import Reviewer


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
    reviewer: Reviewer
    """人与图之间的门（插话 + 审）。没接控制台时是 `NullReviewer`。"""
    planner: Planner
    """plan 位置的 input 来源（给出一版目标表）。**没接控制台时是 `BrainPlanner`**
    ——模型自主规划（0914 S2 起的缺省，见 `build.py`）；要"不加目标、不表态"
    得显式传 `NullPlanner()`（`null_reviewer.py`）。

    **它取代了旧的 `interaction`**（0914 控制台改造）：那个信箱是"前端在另一个
    线程里异步回话"的形状；控制台里人就在图的调用栈上，所以这里改成两个
    同步接口。**恒非空**——装配处保证（`reviewer` 缺省 `NullReviewer`、
    `planner` 缺省 `BrainPlanner`，见 `build.py`），于是节点里不再需要
    那一串 `assert interaction is not None`。
    """

    # ---- 开关：构造时定，整 run 不变 ----

    auto_push_goals: bool = True
    """`False` 时 `plan` 丢弃 planner 给的新目标（人工通道不受影响）。"""
    auto_decide_done: bool = True
    """`False` 时 `plan` 没有权力让 run 结束——表空也只去 `review` 问人。"""

    # ---- 记号：整 run 的 ----

    run_id: str = "local"
    """这次 run 的标识：拼截图路径、标 `EpisodeMemory.run_id`、给事件盖 `run_id`。"""
    world_reset_done: bool = False
    """世界起点存档读过了没有（`_begin` 是唯一读点）。

    **不落盘**，但**两处都要显式写**：`_begin`（首局 reset 后）与未来的恢复入口
    ——后者不能省：恢复路径不经过 `_begin`，而本局跑完后**下一局的 `_begin` 会读它**，
    少写一处的症状是"能恢复、能跑完本局，但下一局世界回退到 ROM 起点"。
    """

    # ---- 账：键里带 episode_id（没有"每局要清"的东西） ----

    frame_before: tuple[str, int, str] | None = None
    """**这一步**开局画面的 `(episode_id, step, base64 PNG)`——帧槽的 `before` 位。

    写入口只有一个：`episode/episode_frames.remember_frame()`（产出方是图外的
    `begin_episode` 与图内每键的 `perceive_after_action`）。**唯一读者**是步尾
    `store_step_episode_memory` 的 `before_frame`。
    """
    frame_after: tuple[str, int, str] | None = None
    """**下一步**开局画面的 `(episode_id, step, base64 PNG)`——帧槽的 `after` 位。

    写新帧时旧的 `after` 被挪进 `frame_before`（"为什么恰好两步"、跨局清空，都在
    `episode_frames.remember_frame` 的 docstring 里）。它的唯一读者是步尾
    `store_step_episode_memory` 的 `after_frame`。

    **帧槽是画面唯一的取用通道**（0914 封套改造）：事件不再自带 `frame_png`，
    原先"槽未命中就按 `frame_event_ids` 回盘"那一级连同登记表一起删了。跨进程时
    槽必然是空的——那时就是没有图，不再有兜底。
    """


__all__ = ["HarnessDeps"]
