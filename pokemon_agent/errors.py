"""预期内失败的跨层异常。

模块内部的失败词汇各自归模块所有，不继承本文件的 `AgentError`。
大脑的 `AttemptFailed` 由 tool 层 `BrainTool._attempt_loop` 捕获并翻译；
重试耗尽才以 `MaxRetriesExceeded` 跨到 harness，由调用节点决定结算方式。

`BudgetExhausted` 表示剩余预算不够，harness 直接机械收尾，不作为模型失败重试。
world 的视觉感知调用链已从 tool 层移除，不再在这里翻译它的内部异常。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 只在类型层面需要：`MaxRetriesExceeded.calls` 是**跨层信封那份**
    # `ModelCall`（实体住 `schemas/harness/communication/ModelCall.py`，
    # 由 `schemas/harness/__init__.py` 出口）——brain 交出来的方言账已由
    # `BrainTool._adopt()` 翻译成这一份，是 tool 层的工作形状。
    # 运行时完全不碰它（`list(calls)` 只迭代实参），且 `from __future__ import
    # annotations` 让签名注解都是字符串，所以放 TYPE_CHECKING 即可。
    from pokemon_agent.schemas.harness import ModelCall


class AgentError(Exception):
    """本项目所有预期内失败的基类。捕获它意味着"我知道这里会出问题"。

    **它不是"所有模块异常的共同祖先"**（docstring 曾这么写，0915 更正）——
    brain/world 的异常 0913 起各自成根（`BrainError`/`WorldError`），在 tool 层
    的桥上就被翻译掉，走不到 harness 的捕获点；真正继承它的只有本文件的
    `MaxRetriesExceeded`。见本文件模块 docstring 的"跨桥判据"。
    """


class BudgetExhausted(AgentError):
    """剩余时间不足以启动一次有用请求；由 harness 机械结算，不作为模型重试。"""

    def __init__(
        self, source: str, calls: Sequence[ModelCall] = (), reason: str = "time_exhausted"
    ) -> None:
        """保留耗尽原因和此前完成的调用账；未发出的请求不虚构调用账。"""
        super().__init__(f"[{source}] {reason}")
        self.source = source
        self.reason = reason
        self.calls = list(calls)


class MaxRetriesExceeded(AgentError):
    """连续重试仍拿不到可用结果。

    到这一步说明模型在当前状态下持续失败，是一条要进 trace 并被 replay 统计的失败模式，
    不是"再试试就好"。

    **谁抛**：tool 层的 `BrainTool._attempt_loop`（各条大脑链路统一重试
    `BRAIN_MAX_ATTEMPTS` 次）。
    **谁接**：harness 的调用点——它决定这一局/这一轮怎么收场（`choose` 耗尽让这一局
    失败，`plan` 耗尽路由 review 交人工，等）。

    **它为什么不进 brain**（0913）：brain 只回答"这一次成没成"（抛 `AttemptFailed`），
    不含"重试几次""耗尽之后怎么办"这些**调用方处境**的知识。循环在 tool 层，所以这个
    "预算耗尽"的升级态也归 tool 层宣布。它留在顶层是因为**抛的人（tool）与接的人
    （harness）分属两层**，它不属于任何单一一层。

    `calls`：**整条失败账**（每一次尝试的 `ModelCall`，按发生顺序），可空——
    循环在 `BrainTool` 里，它把账打包随异常带出来，宿主节点一步落账，
    不用再回头找中间状态。**类型是跨层信封那份 `ModelCall`**
    （`schemas/harness/communication/ModelCall.py`）——brain 交出来的方言账
    由 `BrainTool._adopt()` 翻成这一份。**账上没有"第几次尝试"字段**：
    每条账各代表一次尝试，所以尝试次数就是 `len(calls)`。

    `source`：哪条链路耗尽（`"choose"` / `"plan"` / `"judge"` / `"verify"` /
    `"decompose"` / `"summarize_episode"` / `"summarize_task"` / `"sense"`）。
    同一个异常类被各条链路共用，
    `source` 是调用方分辨"是谁完了"的依据——没有它就只能靠调用点位置倒推，
    而重试循环在 tool 层，调用点与链路已不是一一对应。
    """

    def __init__(
        self,
        attempts: int,
        last_reason: str,
        calls: Sequence[ModelCall] = (),
        source: str = "",
    ) -> None:
        """记下试了几次、最后一次为什么失败、整条账、以及哪条链路。"""
        label = source or "unknown"
        super().__init__(f"[{label}] gave up after {attempts} attempts, last: {last_reason}")
        self.attempts = attempts
        self.last_reason = last_reason
        self.calls: list[ModelCall] = list(calls)
        self.source = source


class NoGoalToDispatch(AgentError):
    """`plan_run` 规划完，目标表里仍没有一条 `PENDING`——run 未判停却无事可派。

    fail-fast：停机只由 `review_and_judge` 判，规划给不出目标不是"该停了"的信号。
    """


__all__ = ["BudgetExhausted", "AgentError", "MaxRetriesExceeded", "NoGoalToDispatch"]
