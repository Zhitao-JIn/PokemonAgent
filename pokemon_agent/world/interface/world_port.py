"""世界接口：模拟器 + 视觉模型抽象成的那一层。

**物理位置**：原来在顶层 `pokemon_agent/interfaces/world/`，跟这个子系统吐出来的
数据形状（`Facts`，同目录 `domain/facts.py`）搬到了一起——协议和协议吐出来的数据
形状本来就是同一件事的两个角度，没道理分居两处。`pokemon_agent/interfaces/` 这个
集中注册表已经整个撤销，消费方直接 `from pokemon_agent.world import WorldPort`。

**零依赖**：`brain`/`world`/`memory`/`trace` 这几个领域模块之间、以及它们与
`schemas.*` 之间，原则是完全没有相互依赖——模块间只靠裸函数和 tool 层交互
（`providers` 例外，当作底层公共库，各模块都能直接依赖）。这个协议原来收
`Action`/`Task`（来自 `pokemon_agent.brain`）、返回
`schemas.world.communication.PerceiveOnceResp`（来自 `schemas`）——两条依赖
都得去掉：

- `reset()`/`set_task()` 不再收 `Task` 这个 brain 的类型，改收裸字段
  （`task_id`/`goal`/`success_criteria`/`max_steps`/`initial_state_hint`）——
  world 本来就只用得到这几个原始值，`Task` 剩下的字段（比如给 LLM
  读的 `goal` 怎么措辞）它从来不关心。
- `step()` 不再收 `Action` 这个 brain 的类型，改收
  `list[tuple[str, int]]`（按键名 + 连按次数的按键段列表）——world 只关心
  "按哪个键、按几次"，不关心 brain 的动作类型。
- `perceive_once()` 不再返回 `schemas` 里的信封，改返回 `Perceived`
  （`domain/perceived.py`）——world 自己的数据形状，不是"两个模块协商出的
  信封"。

`mcpclient/game_tools.py`（`GameToolPort` 的实现）是唯一的调用方，负责把
harness 那一侧的 `Task`/`Action`/信封拆成这里要的裸字段，
再把这里吐出来的 `Perceived` 拼回 harness 认识的信封——这正是"tool 层承接
拆信封/拼信封"这条分工在 world 这一侧的落地。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain import ActionSpace, MacroOutcome, Perceived, TaskPerceived


@runtime_checkable
class WorldPort(Protocol):
    """一个可推进、可观测的世界。"""

    def reset(
        self,
        *,
        task_id: str,
        goal: str,
        success_criteria: str,
        max_steps: int,
        initial_state_hint: str = "",
    ) -> None:
        """按任务重置到初始状态。**不感知**——第一帧由调用方另调 `perceive_once()` 拿。

        参数是 `Task` 拆开的裸字段——world 只用得到这几个原始值。
        前置条件：max_steps > 0。
        """
        ...

    def get_action_space(self) -> ActionSpace:
        """按**当前这一帧**算此刻的能力掩码：原子键与宏在同一命名空间。

        **为什么这一条从 tool 层搬进 world**（2026-09-29）：掩码的依据是当前帧的
        overlay 与场合，而"当前帧"只有 world 有——MCP 化之后 world 住在独立
        进程里，tool 层在另一个进程拿不到帧，算不出来。进程内模式下
        `mcpclient/game_tools.py` 仍可（也应当）按调用方交出的那份观测算，
        两边共用 `world/action_space.py::compute_action_space` 这一个纯函数。

        返回 `ActionSpace`：`mask`（名字 → 此刻是否可用，覆盖全部键 + 本场合
        的宏）、`entries`（各条目的参数签名与说明）、`scene`。

        前置条件：已 `reset()`（要读当前帧）。
        后置条件：至少有一个 enabled 的动作。
        """
        ...

    def all_actions(self) -> list[str]:
        """列出这个世界支持的全部动作名（**与状态无关**）。

        **P2 起不再是"掩码"的入口**——掩码走 `get_action_space()`。本方法只剩
        一个用途：给调用方枚举命名空间的全体（`mask` 里 False 的那些也要有名字）。
        """
        ...

    def step(self, segments: list[tuple[str, int]], *, settle: bool = True) -> None:
        """执行动作，推进世界。**不感知**——之后那一帧由调用方另调
        `perceive_once()` 拿。

        segments：按序执行的按键段，每段是 `(按键名, 连按次数)`——
            `Action.sequence` 拆开的裸字段。执行层恒传单键（一段、一次）。
        settle：按完之后要不要给世界一段**无输入演化时间**再交回控制权。
            `True` = 等（换图的淡入淡出、战斗开场动画、对话逐字打出、菜单弹出
            这些"按下去之后自己会走完"的过程都在这一段里走完）；
            `False` = 按完即返回——链中间的键用这一档，后面还有键要按。
            **它不改变按键本身的效果**，只改变调用方什么时候拿到控制权；
            代价是 `False` 那一档可能抄到过场的中间帧。
        前置条件：每一段的按键都在 all_actions() 中；当前 episode 未结束。
        失败：按键不在 all_actions() 是调用方 bug，assert 拦下。
        """
        ...

    def perceive_once(self) -> Perceived:
        """感知当前这一帧（episode 层的视觉档）。

        **只问一次视觉模型，不重试**。调用方在
        `reset()`/`step()` 之后调它拿观测；重试预算与循环归调用方管
        （`mcpclient/game_tools.py::GameTools.perceive_with_retry`——0913 夜从
        harness 节点搬回 tool 层，与 `BrainTool._attempt_loop` 同形）。
        失败：解析不出结构化状态时抛 `PerceptionAttemptFailed`（附这次的账）——
            要不要再问一次是调用方的判断。

        后置条件：返回时 observation 非空，且是这次真调用产生的新观测。
        """
        ...

    def run_macro(self, name: str, args: dict[str, str | int]) -> MacroOutcome:
        """在当前接管场合执行一个宏，执行到底再返回（回初态 → 校验 → 逐步执行 → 收尾）。

        name / args：宏名与参数（签名见 `macro_specs(scene)`）。
        后置条件：返回时世界停在宏的收尾处（初态或已离开场合）。
        失败：未知宏、参数不合法、执行中途走偏都作为结果返回
            （`rejected` / `aborted` / `left_scene`），不抛异常。
        """
        ...

    def perceive_task(self) -> TaskPerceived:
        """感知当前这一帧（task 层）：**不调视觉模型**，只读内存与屏幕缓冲。

        返回的 `TaskObservation` 带场合（`scene`），`perceived=False`；画面字段二选一——
        屏上有字只给 `screen`，没字只给 `walk_map`。
        前置条件：已 `reset()`。
        后置条件：不会失败；返回的是此刻的新观测。
        """
        ...

    def save_state(self) -> bytes:
        """把模拟器的**完整状态**（CPU、内存、画面）导出成字节串。**不推进世界**。

        给 checkpointer 用：与 `load_state` 成对，`load_state(save_state())` 之后
        世界与导出那一刻逐字节相同。
        后置条件：返回非空字节串。
        """
        ...

    def load_state(self, data: bytes) -> None:
        """用 `save_state` 导出的字节串把模拟器**原样**恢复到那一刻。**不推进世界**。

        不在读档后 tick：读档本身已恢复画面与内存，多推一帧会让恢复点偏离存档点。
        前置条件：`data` 是本世界 `save_state` 的产物（非空）。
        """
        ...
