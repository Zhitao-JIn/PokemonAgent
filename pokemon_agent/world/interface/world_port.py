"""世界接口：用裸字段推进模拟器，读取确定性的内存观测。

模块不认识 harness 信封；双向转换由 tool 层完成。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain import ActionSpace, TaskPerceived


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
        start_state: bytes | None = None,
    ) -> None:
        """按任务重置到初始状态。**不感知**——第一帧由调用方另调 `perceive_task()` 拿。

        参数是 `Task` 拆开的裸字段——world 只用得到这几个原始值。
        start_state 非 None 时用该字节起点重置，不读 state_path、不走开机；
        不给则保留原来的起点行为。
        前置条件：max_steps > 0；给了 start_state 则必须非空。
        """
        ...

    def get_action_space(self) -> ActionSpace:
        """按**当前这一帧**算此刻的能力掩码：原子键与脚本在同一命名空间。

        **为什么这一条从 tool 层搬进 world**（2026-09-29）：掩码的依据是当前帧的
        overlay 与场合，而"当前帧"只有 world 有——MCP 化之后 world 住在独立
        进程里，tool 层在另一个进程拿不到帧，算不出来。进程内模式下
        `mcpclient/game_tools.py` 仍可（也应当）按调用方交出的那份观测算，
        两边共用 `world/action_space.py::compute_action_space` 这一个纯函数。

        返回 `ActionSpace`：`mask`（名字 → 此刻是否可用，覆盖全部键 + 本场合
        可用的脚本）、`entries`（各条目的参数签名与说明）、`scene`。

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
        `perceive_task()` 拿。

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

        导出模拟器完整状态，供需要保存当前世界状态的调用方使用；与 `load_state` 成对，
        `load_state(save_state())` 之后世界与导出那一刻逐字节相同。
        后置条件：返回非空字节串。
        """
        ...

    def read_wram(self) -> bytes:
        """数据集冻结用的只读口：返回 0xC000–0xDFFF，不推进世界。

        后置条件：返回恰好 8192 字节；长度违约时实现断言失败。
        """
        ...

    def load_state(self, data: bytes) -> None:
        """用 `save_state` 导出的字节串把模拟器**原样**恢复到那一刻。**不推进世界**。

        不在读档后 tick：读档本身已恢复画面与内存，多推一帧会让恢复点偏离存档点。
        前置条件：`data` 是本世界 `save_state` 的产物（非空）。
        """
        ...
