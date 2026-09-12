"""`BrainTool` → `Brain` 这一跳的决策响应协议：`ChooseOnceResp`。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import ActionFromBrain
from pokemon_agent.providers.interface import ModelCall


class ChooseOnceResp(BaseModel):
    """**`Brain.choose_once()` 一次尝试成功时的全部产物**：动作、这次的账、
    它翻过哪些记忆。

    只在成功路径上用——失败（解析不出来 / 选了不存在的键 / 被截断）时
    `choose_once()` 抛 `DecisionAttemptFailed`（附这次的账），不走这个 resp，
    所以 `action` 不会是 `None`；`calls` 也恰好一条（这次尝试自己的账），
    多次尝试的累积在 Harness 那层的 `brain_utils.choose_with_retry` 做，
    不在这里滚存。
    """

    action: ActionFromBrain = Field(description="这次尝试解析出的合法动作")
    calls: list[ModelCall] = Field(
        min_length=1, max_length=1, description="这次尝试自己的账，恰好一条"
    )
    recalled: list[str] = Field(
        default_factory=list,
        description="取回了哪几条情景记忆，形如 `(episode_id, step)`（`req.memories`"
        "的原样投影）。**记引用而不只是条数**——只记数量的话，replay 时无法回答"
        "「这个决策是被哪条经验影响的」，而那正是「记忆到底有没有用」要查的东西",
    )
