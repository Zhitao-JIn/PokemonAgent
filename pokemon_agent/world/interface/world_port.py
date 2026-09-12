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
  "按哪个键、按几次"，不关心 `Action.thought`/`rationale` 这些只有
  brain/trace/memory 关心的字段。
- `perceive_once()` 不再返回 `schemas` 里的信封，改返回 `Perceived`
  （`domain/perceived.py`）——world 自己的数据形状，不是"两个模块协商出的
  信封"。

`tools/game_tools.py`（`GameToolPort` 的实现）是唯一的调用方，负责把
harness 那一侧的 `Task`/`Action`/信封拆成这里要的裸字段，
再把这里吐出来的 `Perceived` 拼回 harness 认识的信封——这正是"tool 层承接
拆信封/拼信封"这条分工在 world 这一侧的落地。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain import Perceived


@runtime_checkable
class WorldPort(Protocol):
    """一个可推进、可观测的世界。"""

    def save_state(self, path: str) -> None:
        """把世界当前状态存到 path。

        path：存档文件路径。
        """
        ...

    def save_state_bytes(self) -> bytes:
        """把世界当前状态存成字节串（checkpoint 每步世界快照用）。

        后置条件：返回的字节串能被 `load_state_bytes` 原样恢复。
        """
        ...

    def load_state_bytes(self, data: bytes) -> None:
        """从字节串恢复世界状态（checkpoint 恢复用）。

        前置条件：`data` 来自同一 ROM 的 `save_state_bytes()`。
        后置条件：模拟器回到快照那一刻的状态（画面恢复由下一次 tick 完成）。
        """
        ...

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

    def set_task(
        self,
        *,
        task_id: str,
        goal: str,
        success_criteria: str,
        max_steps: int,
        initial_state_hint: str = "",
    ) -> None:
        """只挂任务标记，**不动模拟器状态**（checkpoint 恢复后配 `load_state_bytes` 用）。

        前置条件：max_steps > 0；`load_state_bytes()` 已经把模拟器摆到了正确的帧。
        后置条件：`_task`/`_closed` 就位，`step()`/`perceive_once()` 的前置断言不再拦它。
        """
        ...

    def all_actions(self) -> list[str]:
        """列出这个世界支持的全部动作名。

        后置条件：非空，且整个 episode 内不变。
        """
        ...

    def step(self, segments: list[tuple[str, int]], *, settle: bool = True) -> None:
        """执行动作，推进世界。**不感知**——之后那一帧由调用方另调
        `perceive_once()` 拿。

        segments：按序执行的按键段，每段是 `(按键名, 连按次数)`——
            `Action.sequence` 拆开的裸字段，world 不需要知道
            `thought`/`rationale` 这些字段。执行层恒传单键（一段、一次）。
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

    def perceive_once(self, *, ram_only: bool = False) -> Perceived:
        """感知当前这一帧。

        `ram_only=False`（缺省）：**只问一次视觉模型，不重试**。调用方在
        `reset()`/`step()` 之后调它拿观测；重试预算与循环归调用方管
        （见 `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"）。
        失败：解析不出结构化状态时抛 `PerceptionAttemptFailed`（附这次的账）——
            要不要再问一次是调用方的判断。

        `ram_only=True`：**不调视觉模型**，只读内存里确定的那几样——坐标、朝向、
        地标、通行图、地图编号。返回的观测 `perceived=False`：场景与对话
        **不是空的，是没读过**。`calls` 为空，也不会失败。链中间的键用这一档，
        它们只需要判"位置动没动、换没换图"，为此烧一次视觉调用买的是用不上的信息。

        后置条件：返回时 observation 非空，且是这次真调用产生的新观测。
        """
        ...
