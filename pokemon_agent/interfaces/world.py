"""世界的接口：模拟器 + 视觉模型被抽象成的那一层。

之下唯一的实现是 `world/pyboy_world.py`。这一层的意义是让上面换模拟器、
换视觉模型时一行不用改——**它只回答"世界现在什么样、按下去会怎样"**，
不数步数、不判成败、不碰记忆。

两条要点：

- **`observe()` 幂等，`step()` 不幂等。** 同一帧内重复 `observe()` 不该产生额外的
  模型调用（实现方要按帧缓存）——感知是每步都要付钱的那一项。
- **模型调用记录跟着返回值走。** `PerceptionResult.calls` / `ToolResult.calls` 由
  产生调用的方法原样交出来，调用方当场记账，没有任何跨调用的缓冲区。
  这一条是踩出来的：上一版靠 `drain_calls()` 攒着给别人来取，清早清晚都能把账算错。

`Observation.step` 在这一层是**占位值**：世界不知道自己在第几步，盖章是 Harness 的事。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.action import Action, ToolResult
from pokemon_agent.schemas.observation import PerceptionResult
from pokemon_agent.schemas.task import Task


@runtime_checkable
class WorldPort(Protocol):
    def save_state(self, path: str) -> None:
        """保存当前模拟器状态，供 episode replay 使用。"""
        ...
    """一个可推进、可观测的世界。"""

    def reset(self, task: Task) -> PerceptionResult:
        """按任务重置到初始状态并返回首个观测。

        任务由外部传入而非 world 自选：**同一个世界要能跑不同任务**，
        否则没法按 task_id 分组统计成功率。

        前置条件：task.max_steps > 0。
        后置条件：返回的 `result.observation.done` 为 False（`step` 由 Harness 盖章）；
            `result.calls` 是这次重置期间产生的模型调用记录（通常来自随后那次感知）。

        **world 不需要知道任务目标。** `task` 传进来是为了让同一个世界能按不同任务
        选不同的起始状态（现在还没用上，恒是同一个存档），以及断言 `max_steps > 0`。
        "现在要完成的是哪条目标"由 Harness 的目标栈保管，随 `brain.choose` 下发。

        把世界恢复到任务起点，返回第一帧观测。
        """
        ...

    def observe(self) -> PerceptionResult:
        """取当前观测，不推进世界（幂等）。

        后置条件：`result.calls` 非空当且仅当这次调用真的调了视觉模型；
            命中缓存时是空列表，**不是 None**。

        读当前这一帧，不推进世界。
        """
        ...

    def all_actions(self) -> list[str]:
        """世界支持的**全部**动作名（与当前状态无关）。

        后置条件：非空，且内容在整个 episode 内不变。
            这是 masking 的全集，harness 从中筛出当前可用的子集。

        列出这个世界支持的全部动作名。
        """
        ...

    def step(self, action: Action) -> ToolResult:
        """执行**整条动作链**，推进世界，**只在链的结尾感知一次**。

        `action.segments()` 里的每一段按 `times` 次，段与段之间不感知——
        一次决策 = 一次感知，这是成本的硬约束：每次感知都是一次视觉模型调用。
        中间帧因此看不到，这是有意的取舍，见 `Action.sequence` 的规则
        （多段链只能是移动键，移动的中间帧没有证据）。

        前置条件：每一段的按键都在 all_actions() 中；且当前 episode 未结束（done 为 False）。
        后置条件：若返回的 observation 非空，其 step 等于调用前的 step + 1；
            达成 task 的成败判据或用满 max_steps 时，observation.done 为 True。
            **成败判定属于 world**——只有它知道游戏状态是否满足判据。
            `result.calls` 含推进这一步期间产生的模型调用记录（通常来自
            推进后重新感知那一次）；命中缓存时为空列表。
        失败：动作合法但没成功走 ok=False，不抛异常；
            某一段的按键不在 all_actions() 中是**调用方的 bug**，assert 拦下。

        按完整条动作链，推进世界一步，返回结果与新观测。
        """
        ...
