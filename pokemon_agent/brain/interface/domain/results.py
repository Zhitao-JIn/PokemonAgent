"""大脑各方法一次调用的产物：`ChooseResult`/`JudgeResult`/`PlanResult`/
`DecomposeResult`/`VerifyResult`/`SummarizeResult`。

**每个结果袋都是"硬性字段 + 软性字典"这个形状**——硬性字段是调用方一定要的
（少一个就没法继续），`extra` 吸收其余一切：模型多给的字段、实现临时加的
说明、prompt 里的额外要求产出的东西。**契约因此不必随每次调整而改**：
prompt 里加一条"顺便告诉我你有多确信"，产出直接进 `extra`，签名一个字不动。

写 `extra` 的判据：**调用方不必为了继续而读它**。一旦某个字段是"没有它就没法
继续"，它就该升格成硬性字段，而不是留在 `extra` 里等人去翻。

**账（`calls`）也在这里**：一次模型调用 = 一条账。一次调用的尝试次数是
`len(calls)`，`extra` 里不再另记一份。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .action import Action
from .decomposition import Decomposition
from .episode_summary import EpisodeSummary
from .model_call import ModelCall
from .run_plan import RunPlan
from .verify_verdict import VerifyVerdict


class _ResultBase(BaseModel):
    """结果袋的公共底座：软性字典。

    抽出来只为让"每个结果袋都带 `extra`"这件事在代码里可见，不做别的。
    """

    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="这次调用的额外产物——模型多给的字段、prompt 额外要求产出的"
        "东西。**调用方不必为了继续而读它**，读不到也不影响主流程",
    )


class ChooseResult(_ResultBase):
    """**`choose()` 一次成功调用的产物**：动作 + 这次尝试的账。

    `action` 的 postcondition：`action.sequence` 里每个 `name` 都在调用方给的
    `keys` 里——大脑不会幻觉出不存在的按键。
    """

    action: Action = Field(description="这次尝试解析出的合法动作")
    calls: list[ModelCall] = Field(
        default_factory=list,
        description="这次尝试自己的账，恰好一条。类型是 `brain.interface.ModelCall`"
        "——brain 方言里的形状，不是 tool 层那一份（见 `model_call.py` 的说明）",
    )


class JudgeResult(_ResultBase):
    """**`judge()` 的产物**：任务达成了没有、依据是什么、花了什么。

    失败时**抛 `JudgeAttemptFailed`**（不再静默返回 `done=False`）——
    那条旧契约让"判定器坏了"与"真的没达成"在数据里分不开。
    """

    done: bool = Field(description="任务达成了没有")
    interrupted: bool = Field(
        default=False,
        description="模型判这件事被意外打断了"
        "（输出里有布尔 `interrupted` 且 `done` 为假时才可能为真）",
    )
    why: str = Field(
        description="看到了什么证据（或为什么证据不足）。"
        "每一个 True 都得说得出依据，否则成功率就是一个无法证伪的数字"
    )
    calls: list[ModelCall] = Field(default_factory=list, description="这次判定的账，恰好一条")


class PlanResult(_ResultBase):
    """**`plan()` 一次成功调用的产物**：解析出的计划 + 这次尝试的账。"""

    plan: RunPlan = Field(description="这次尝试解析出的计划")
    calls: list[ModelCall] = Field(default_factory=list, description="这次尝试自己的账，恰好一条")


class DecomposeResult(_ResultBase):
    """`Brain.decompose()` 的结果袋。失败抛 `DecomposeAttemptFailed`（附这次的账）。"""

    decomposition: Decomposition = Field(description="这次尝试解析出的任务链")
    calls: list[ModelCall] = Field(default_factory=list, description="这次尝试自己的账，恰好一条")


class VerifyResult(_ResultBase):
    """**`verify()` 的产物**：逐条判定 + 这次的账。

    `verdicts` 与调用方给的 `count` **等长**（按 `index` 顺序补齐）。
    **过滤归调用方**：本方法只判、不过滤，谁想用可信的那部分自己筛——
    `summarize()` 就收筛完之后的历史。

    **解析失败时抛 `VerifyAttemptFailed`**，不再返回"全部标不可靠"——
    那份保守结果与"这一局记忆确实都不可信"在数据上无法区分。
    """

    verdicts: list[VerifyVerdict] = Field(description="与 count 等长的判定列表")
    calls: list[ModelCall] = Field(default_factory=list, description="这次校验调用的账")


class SummarizeResult(_ResultBase):
    """**`summarize()` 的产物**：蒸馏出的本局摘要 + 这次的账。

    `summary` **非 Optional**：解析/调用失败时抛 `SummarizeAttemptFailed`——
    旧契约的 `None` 让"链路坏了"与"这局确实没什么可总结"分不开。
    """

    summary: EpisodeSummary = Field(description="蒸馏出的本局摘要")
    calls: list[ModelCall] = Field(default_factory=list, description="这次蒸馏调用的账")

