"""MCP 工具层 —— 大脑与外界的**唯一**通信边界。

这是整个架构最重要的一个文件：铁律 2 说大脑只能通过这里与外界交互，
所以**这五个方法就是大脑能力的全集**。往里加方法前先问一句：
这是大脑该知道的事，还是 harness 内部的事？

设计文档对应「MCP 层（暴露给大脑的全部接口）」。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.core import (
    Action,
    ActionSpace,
    MemoryEntry,
    Observation,
    ToolResult,
)


@runtime_checkable
class ToolPort(Protocol):
    """harness 暴露给大脑的五个工具。

    实现方（harness）持有全部状态；调用方（大脑）不持有任何状态。
    这个接口是那条边界的**唯一**通道。
    """

    def perceive(self) -> Observation:
        """取当前观测。

        后置条件：返回的 observation.step 单调不减（同一步内多次调用返回相同 step）；
            observation.goal 是当前 episode 所属任务的目标。
        注意这是**幂等**的：只读，不推进世界。推进只发生在 execute()。
        """
        ...

    def get_action_space(self) -> ActionSpace:
        """取当前状态下可用的动作（含 masking）。

        后置条件：`names` 非空。
            走投无路的状态也必须至少给一个动作（如 `wait`）——
            空动作空间是 harness 的 bug，不能让大脑去处理这种情况。
        """
        ...

    def execute(self, action: Action) -> ToolResult:
        """执行一个动作，推进世界。

        前置条件：action.name 属于**调用前最近一次** get_action_space() 的结果。
            实现方必须 assert 这一点——大脑幻觉出不存在的动作会在这里就地爆炸，
            而不是变成一个语义不明的模拟器错误。
        后置条件：返回 ok=False 表示动作合法但没成功（撞墙、道具不足），
            这是**预期内的游戏事件**，不抛异常。
        """
        ...

    def memory_query(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """检索相关记忆。

        前置条件：limit > 0。
        后置条件：返回条数 <= limit；按相关性降序。
            **检索策略属于实现方**——大脑不知道也不该知道记忆从哪来、怎么排的，
            机制一、机制三接进来时改的是实现，这个签名不动。
        """
        ...

    def memory_write(self, entry: MemoryEntry) -> None:
        """写入一条记忆。

        前置条件：entry.content 非空。
        注意：harness 也可能自动写记忆。**大脑不能假设记忆库里只有自己写的东西。**
        """
        ...
