"""`GameToolPort`：Harness 操作世界的工具门面——执行、开局、存档、动作空间。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolEvolveReq,
    FromHarnessToGameToolExecuteReq,
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToGameToolGetActionSpaceResp,
    FromHarnessToGameToolLoadStateBytesReq,
    FromHarnessToGameToolPerceiveOnceResp,
    FromHarnessToGameToolResetReq,
    FromHarnessToGameToolSaveStateBytesResp,
    FromHarnessToGameToolSaveStateReq,
    FromHarnessToGameToolSetTaskReq,
)


@runtime_checkable
class GameToolPort(Protocol):
    """Harness 操作世界的接口：执行、开局、存档。

    这是第一跳（harness → 门面），入参与返回一律是信封；门面往里调 world
    走裸参数，那一跳不造信封。
    """

    def save_state(self, req: FromHarnessToGameToolSaveStateReq) -> None:
        """把世界当前状态存成文件。

        req.path：存档文件路径。
        """
        ...

    def save_state_bytes(self) -> FromHarnessToGameToolSaveStateBytesResp:
        """把世界当前状态存成字节串（checkpoint 每步世界快照用）。"""
        ...

    def load_state_bytes(self, req: FromHarnessToGameToolLoadStateBytesReq) -> None:
        """从字节串恢复世界状态（checkpoint 恢复用）。

        req.emulator_state：要回载的世界快照字节。
        """
        ...

    def get_action_space(
        self, req: FromHarnessToGameToolGetActionSpaceReq
    ) -> FromHarnessToGameToolGetActionSpaceResp:
        """按当前 overlay 给出此刻能按的键。

        req.observation：当前观测。
        后置条件：resp.action_space.names 非空。
        """
        ...

    def execute(self, req: FromHarnessToGameToolExecuteReq) -> None:
        """执行一个动作，推进世界。**不感知**——调用方另调 `perceive_once()` 拿新观测。

        req.action：要执行的动作（可能是动作链）。
        req.observation：这个动作据以选出的那份观测。
        前置条件：动作每一段的按键属于 get_action_space(req.observation) 的结果（实现方 assert）。
        """
        ...

    def reset(self, req: FromHarnessToGameToolResetReq) -> None:
        """按任务重置到初始状态。**不感知**——调用方另调 `perceive_once()` 拿第一帧。

        req.task：要跑的任务。
        前置条件：req.task.max_steps > 0。
        """
        ...

    def set_task(self, req: FromHarnessToGameToolSetTaskReq) -> None:
        """只挂任务标记，**不动模拟器状态**（checkpoint 恢复后配 `load_state_bytes` 用）。

        req.task：要接上跑的任务。
        前置条件：req.task.max_steps > 0；`load_state_bytes()` 已经把模拟器摆到了正确的帧。
        """
        ...

    def perceive_once(self) -> FromHarnessToGameToolPerceiveOnceResp:
        """感知当前这一帧，**只问一次视觉模型，不重试**。

        调用方在 `reset()`/`execute()` 之后调它拿观测；重试预算与循环归
        调用方（Harness）管，见 `docs/ROADMAP.md`。
        后置条件：resp.perceived.observation 非空；step 未盖章（Harness 的事）。
        失败：解析不出结构化状态时抛 `PerceptionAttemptFailed`（附这次的账）。
        """
        ...

    def evolve(self, req: FromHarnessToGameToolEvolveReq) -> None:
        """**无输入**推进 N 帧——世界自己演化（音乐、动画、NPC 走动），不感知。

        和按键后的演化是同一回事，只是独立于按键被调用：harness 在等决策 LLM
        返回时用它填空闲窗口，让画面/音乐继续（见 `episode_harness.think`）。

        前置条件：req.frames >= 0。
        调用方要保证：这段演化不破坏"观测-决策"一致性——决策期间世界变化是
        **刻意接受的取舍**（决策基于稍早的快照，错位由下一步感知修正），
        感知/判定期间**不能**调用本方法（那要求快照稳定）。
        """
        ...
