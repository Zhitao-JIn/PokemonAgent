"""三层同构的**机械终止类别**：`review_and_judge` 写、`*_done` 与父层读。

与 `reason` 分工：`termination` 是机械结论（枚举，可统计），`reason` 是
`*_done` 里 LLM 写的自然语言说明——前者回答"为什么停"，后者回答"停在哪、
差在哪"。两者都进 `TaskOutput` / `EpisodeOutput`。

**只存 `termination`**：`done`（停没停）与 `success`（成没成）都由它推出，由 `Settled`
统一提供为只读属性——不存第二份，就不会有"done=True 却没有 termination"这种对不上。
"""

from __future__ import annotations

from enum import StrEnum


class Termination(StrEnum):
    """一层循环的终止类别。三层各自独立计数：run 数局、episode 数 task、task 数键。"""

    GOAL_DONE = "goal_done"
    """模型判定本层目标达成（`success` 的唯一来源）。"""
    WORLD_ENDED = "world_ended"
    """世界侧终止（`Observation.done`）。"""
    STALLED = "stalled"
    """停摆：task 连续同键无变化；episode 连续失败 task；run 连续失败局——上限各在 config。"""
    BUDGET_EXHAUSTED = "budget_exhausted"
    """本层计数撞上限：task 键数 / episode task 数 / run 局数。"""
    ERROR = "error"
    """子图抛 `AgentError`，由父层 error handler 兜成的失败结算（只出现在 run 侧）。"""


class Settled:
    """带 `termination` 字段的模型共用的两个派生读法（混入类，自身不声明字段）。

    三层 state 与两个 `*Output` 都混入它：`termination` 为空 = 还没停。
    """

    @property
    def done(self) -> bool:
        """本层停了没有：`termination` 非空。"""
        return getattr(self, "termination", None) is not None

    @property
    def success(self) -> bool:
        """本层目标达成没有：`termination` 是 `goal_done`。"""
        return getattr(self, "termination", None) == Termination.GOAL_DONE


__all__ = ["Settled", "Termination"]
