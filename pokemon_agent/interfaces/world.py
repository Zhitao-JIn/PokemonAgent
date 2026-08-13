"""世界接口 —— harness 底下的那一层，**大脑看不到这个文件**。

为什么要和 ToolPort 分开：
ToolPort 是"大脑能做什么"，WorldPort 是"世界能做什么"，两者职责不同且变化速度不同。
harness 用 WorldPort + 记忆实现 ToolPort。原型期 WorldPort 由 MockWorld 实现，
将来换成真实模拟器时，**ToolPort 和大脑一行都不用改**——这就是分层的收益。

注意这里没有 masking：动作掩码是 harness 的策略，不是世界的能力。
世界只回答"全部动作是什么"和"执行这个动作会怎样"。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.core import Action, Observation, ToolResult


@runtime_checkable
class WorldPort(Protocol):
    """一个可推进、可观测的世界。"""

    def reset(self) -> Observation:
        """重置到初始状态并返回首个观测。

        后置条件：返回的 observation.step == 0 且 done 为 False。
        """
        ...

    def observe(self) -> Observation:
        """取当前观测，不推进世界（幂等）。"""
        ...

    def all_actions(self) -> list[str]:
        """世界支持的**全部**动作名（与当前状态无关）。

        后置条件：非空，且内容在整个 episode 内不变。
            这是 masking 的全集，harness 从中筛出当前可用的子集。
        """
        ...

    def step(self, action: Action) -> ToolResult:
        """执行动作，推进世界。

        前置条件：action.name 在 all_actions() 中。
        后置条件：若返回的 observation 非空，其 step 等于调用前的 step + 1。
        失败：动作合法但没成功走 ok=False，不抛异常；
            action 不在 all_actions() 中是**调用方的 bug**，assert 拦下。
        """
        ...
