"""世界接口 —— harness 底下的那一层，**大脑看不到这个文件**。

为什么要和 GameToolPort 分开：
GameToolPort 是"Harness 能拿世界做什么"，WorldPort 是"世界本身能做什么"，
两者职责不同且变化速度不同。`GameTools` 用 `WorldPort` 实现 `GameToolPort`。
当前唯一的实现是 `PyBoyWorld`，换模拟器时 **GameToolPort 和大脑一行都不用改**——
这就是分层的收益。

注意这里没有 masking：动作掩码是 harness 的策略，不是世界的能力。
世界只回答"全部动作是什么"和"执行这个动作会怎样"。

## 为什么 reset/observe/inspect 返回 PerceptionResult 而不是裸 Observation

感知的开销（token、延迟、模型原始输出）和被感知的那一帧，**两处都放不下**：

- 放不进 `Observation` —— 那是**大脑看的东西**，大脑不该知道 token 数；
  而且它是跨层契约，加字段等于改接口。
- 又必须进 trace —— 没有它，成本拆不开、读错的观测追查不到是哪一帧、
  阶段 3.2 拿 VLM 输出和真值对标也对不上号。

这里曾经用一个 `drain_calls()` 方法外加一个内部缓冲区解决这个矛盾：产生调用
记录的地方先攒到 `self._pending_calls`，Harness 再单独调 `drain_calls()` 取走
清空。这个"生产/消费分离、靠可变状态搭桥"的设计本身就是 bug 的温床——
缓冲区什么时候清、被谁清，两个方向都能错（见 `PerceptionResult` 的完整说明）。

现在改成 `calls` 跟着 `Observation` 一起，作为 `PerceptionResult` 的返回值原样
交出来：产生调用记录的地方直接把它 return 出去，一路跟着 `_perceive()` →
`observe()` → `reset()`/`inspect()` 普通地往上传，不需要任何跨调用的状态。
`step()` 同理，`calls` 就挂在已经存在的 `ToolResult` 上，不必新开一个类型。

不产生模型调用的世界，`calls` 返回空列表即可，这不是负担。
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
        """
        ...

    def observe(self) -> PerceptionResult:
        """取当前观测，不推进世界（幂等）。

        后置条件：`result.calls` 非空当且仅当这次调用真的调了视觉模型；
            命中缓存时是空列表，**不是 None**。
        """
        ...

    def inspect(self, focus: str) -> PerceptionResult:
        """对**同一帧**再问一次感知，问一个具体的问题。世界不推进。

        前置条件：focus 非空。
        后置条件：答案并进观测的 facts；下一次 `step()` 之后自动失效
            （它描述的是那一帧，留到下一帧就是过期事实）。
            `result.calls` 含这次细看产生的调用记录，在前；随后内部再看一眼
            观测（通常命中缓存，不产生新调用）的记录若有，跟在后面。
        失败：**不抛异常**。细看是锦上添花，问不出来就把"没看清"记成答案——
            为它中断一局不划算。

        和 `observe()` 的区别不在"再看一次"，而在**问的是不同的问题**：
        `observe()` 按帧缓存，同一帧再调返回的字节完全一样，没有新信息。
        """
        ...

    def all_actions(self) -> list[str]:
        """世界支持的**全部**动作名（与当前状态无关）。

        后置条件：非空，且内容在整个 episode 内不变。
            这是 masking 的全集，harness 从中筛出当前可用的子集。
        """
        ...

    @property
    def last_frame_sha(self) -> str:
        """最近一次观测所依据的那一帧的哈希。

        没有它，一条读错的观测**无法追查是哪一帧**——而那是查感知错误的起点。
        没有"帧"这个概念的世界返回空串。
        """
        ...

    def step(self, action: Action) -> ToolResult:
        """执行动作，推进世界。

        前置条件：action.name 在 all_actions() 中；且当前 episode 未结束（done 为 False）。
        后置条件：若返回的 observation 非空，其 step 等于调用前的 step + 1；
            达成 task 的成败判据或用满 max_steps 时，observation.done 为 True。
            **成败判定属于 world**——只有它知道游戏状态是否满足判据。
            `result.calls` 含推进这一步期间产生的模型调用记录（通常来自
            推进后重新感知那一次）；命中缓存时为空列表。
        失败：动作合法但没成功走 ok=False，不抛异常；
            action 不在 all_actions() 中是**调用方的 bug**，assert 拦下。
        """
        ...
