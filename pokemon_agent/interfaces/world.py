"""世界接口 —— harness 底下的那一层，**大脑看不到这个文件**。

为什么要和 GameToolPort 分开：
GameToolPort 是"Harness 能拿世界做什么"，WorldPort 是"世界本身能做什么"，
两者职责不同且变化速度不同。`GameTools` 用 `WorldPort` 实现 `GameToolPort`。
当前唯一的实现是 `PyBoyWorld`，换模拟器时 **GameToolPort 和大脑一行都不用改**——
这就是分层的收益。

注意这里没有 masking：动作掩码是 harness 的策略，不是世界的能力。
世界只回答"全部动作是什么"和"执行这个动作会怎样"。

## 为什么有 drain_calls / last_frame_sha

感知的开销（token、延迟、模型原始输出）和被感知的那一帧，**两处都放不下**：

- 放不进 `Observation` —— 那是**大脑看的东西**，大脑不该知道 token 数；
  而且它是跨层契约，加字段等于改接口。
- 又必须进 trace —— 没有它，成本拆不开、读错的观测追查不到是哪一帧、
  阶段 3.2 拿 VLM 输出和真值对标也对不上号。

所以它们进 Port：**世界要能说明"我这次观测是怎么来的"**。
不产生模型调用的世界返回空列表即可，这不是负担。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.action import Action, ToolResult
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.schemas.task import Task


@runtime_checkable
class WorldPort(Protocol):
    """一个可推进、可观测的世界。"""

    def reset(self, task: Task) -> Observation:
        """按任务重置到初始状态并返回首个观测。

        任务由外部传入而非 world 自选：**同一个世界要能跑不同任务**，
        否则没法按 task_id 分组统计成功率。

        前置条件：task.max_steps > 0。
        后置条件：返回的 observation.done 为 False（`step` 由 Harness 盖章）。

        **world 不需要知道任务目标。** `task` 传进来是为了让同一个世界能按不同任务
        选不同的起始状态（现在还没用上，恒是同一个存档），以及断言 `max_steps > 0`。
        "现在要完成的是哪条目标"由 Harness 的目标栈保管，随 `brain.choose` 下发。
        """
        ...

    def observe(self) -> Observation:
        """取当前观测，不推进世界（幂等）。"""
        ...

    def inspect(self, focus: str) -> Observation:
        """对**同一帧**再问一次感知，问一个具体的问题。世界不推进。

        前置条件：focus 非空。
        后置条件：答案并进观测的 facts；下一次 `step()` 之后自动失效
            （它描述的是那一帧，留到下一帧就是过期事实）。
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

    def drain_calls(self) -> list[dict[str, str]]:
        """取走**自上次取走以来**发生的每一次模型调用，并清空。

        后置条件：连着调两次，第二次返回空列表。不调用模型的实现恒返回空列表，
            **不返回 None**。

        ## 为什么是"取走"而不是"最近一次"

        早一版是 `last_calls` 属性，由**生产方**在下一次感知时清空。
        那样它的正确性取决于"记账的人来得够早"，而这个前提两边都会破：

        - 清得太晚（缓存命中时不清）：不推进世界的那些轮次（细看、拆子目标）
          会把上一轮的账**再记一遍**，而且 inspect 的账会被当成 perceive 的账，
          prompt 归因跟着错乱。
        - 清得太早（进门就清）：`reset()` 里那次真实调用的账，会被紧接着那次
          命中缓存的 `perceive()` 冲掉，**钱花了但没有记录**。

        两个方向都错，说明问题不在时机而在归属。改成取走之后，不变量变成
        **每一次调用恰好被记一次账**——它由调用次数本身保证，不依赖调用顺序。

        每条至少含 `input_tokens` / `output_tokens` / `latency_ms` / `attempt` / `ok`；
        `raw`（模型原始输出）建议一并给出——有了它，改进解析器之后能离线重算，
        不必重新花钱调 API。**失败的调用也要在里面**：它们同样烧了 token。
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
        失败：动作合法但没成功走 ok=False，不抛异常；
            action 不在 all_actions() 中是**调用方的 bug**，assert 拦下。
        """
        ...
