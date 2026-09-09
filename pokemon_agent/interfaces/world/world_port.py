"""世界接口：模拟器 + 视觉模型抽象成的那一层。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.communication import FromGameToolToWorldPerceiveOnceResp
from pokemon_agent.schemas.domain import ActionFromBrain, TaskForHarness


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

    def reset(self, task: TaskForHarness) -> None:
        """按任务重置到初始状态。**不感知**——第一帧由调用方另调 `perceive_once()` 拿。

        task：要跑的任务。
        前置条件：task.max_steps > 0。
        """
        ...

    def set_task(self, task: TaskForHarness) -> None:
        """只挂任务标记，**不动模拟器状态**（checkpoint 恢复后配 `load_state_bytes` 用）。

        task：要接上跑的任务。
        前置条件：task.max_steps > 0；`load_state_bytes()` 已经把模拟器摆到了正确的帧。
        后置条件：`_task`/`_closed` 就位，`step()`/`perceive_once()` 的前置断言不再拦它。
        """
        ...

    def all_actions(self) -> list[str]:
        """列出这个世界支持的全部动作名。

        后置条件：非空，且整个 episode 内不变。
        """
        ...

    def step(self, action: ActionFromBrain) -> None:
        """执行整条动作链，推进世界。**不感知**——链尾那一帧由调用方另调
        `perceive_once()` 拿。

        action：要执行的动作链。
        前置条件：每一段的按键都在 all_actions() 中；当前 episode 未结束。
        失败：按键不在 all_actions() 是调用方 bug，assert 拦下。
        """
        ...

    def perceive_once(self) -> FromGameToolToWorldPerceiveOnceResp:
        """感知当前这一帧，**只问一次视觉模型，不重试**。

        调用方在 `reset()`/`step()` 之后调它拿观测；重试预算与循环归调用方
        管（见 `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"）。
        后置条件：返回时 observation 非空，且是这次真调用产生的新观测。
        失败：解析不出结构化状态时抛 `PerceptionAttemptFailed`（附这次的账）——
            要不要再问一次是调用方的判断。
        """
        ...
