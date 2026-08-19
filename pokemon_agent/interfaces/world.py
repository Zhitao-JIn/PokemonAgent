"""世界接口 —— harness 底下的那一层，**大脑看不到这个文件**。

为什么要和 ToolPort 分开：
ToolPort 是"大脑能做什么"，WorldPort 是"世界能做什么"，两者职责不同且变化速度不同。
harness 用 WorldPort + 记忆实现 ToolPort。当前唯一的实现是 `PyBoyWorld`，
换模拟器时 **ToolPort 和大脑一行都不用改**——这就是分层的收益。

注意这里没有 masking：动作掩码是 harness 的策略，不是世界的能力。
世界只回答"全部动作是什么"和"执行这个动作会怎样"。

## 为什么有 last_calls / last_frame_sha

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

from pokemon_agent.schemas.core import Action, Observation, Task, ToolResult


@runtime_checkable
class WorldPort(Protocol):
    """一个可推进、可观测的世界。"""

    def reset(self, task: Task) -> Observation:
        """按任务重置到初始状态并返回首个观测。

        任务由外部传入而非 world 自选：**同一个世界要能跑不同任务**，
        否则没法按 task_id 分组统计成功率。

        前置条件：task.max_steps > 0。
        后置条件：返回的 observation.step == 0、done 为 False、goal == task.goal。
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

    @property
    def last_calls(self) -> list[dict[str, str]]:
        """最近一次 `observe()` 里发生的**每一次**模型调用。

        是列表不是单条：解析失败会重试，而失败的那几次同样烧了 token，
        只留最后一次就把它们的成本和原始输出丢了。

        每条至少含 `input_tokens` / `output_tokens` / `latency_ms` / `attempt` / `ok`；
        `raw`（模型原始输出）建议一并给出——有了它，改进解析器之后能离线重算，
        不必重新花钱调 API。

        后置条件：不调用模型的世界返回空列表，**不返回 None**。
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
