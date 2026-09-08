"""`BrainToolPort`：harness 直接持有的、跟大脑沟通的门面。

跟 `GameToolPort`/`MemoryToolPort` 同一类——harness 的三根依赖(brain/trace/
tools)之一（tools 集合的成员）；不同的是它不做"外部系统原始结构→契约"的
转换，因为 `Brain` 自己已经吃干净了跟 LLM provider 之间的转换。它做的是
**另一件事**：把 harness 自己的契约(`BrainTool*Req`/`Resp`)跟 `Brain` 的
原生契约(`FromBrainToolToBrainChooseOnceReq` 等)显式互转——两跳各自独立的形状，即使今天
翻译就是原样转发，也不能让 harness 直接拿 `BrainPort` 用，那样两边的契约
会被绑死成同一份。

方法名跟 `BrainPort` 一一对应(choose_once/judge/reflect/verify_and_summarize/
plan_once)，故意不改名——方便对照哪个 tool 方法在转发哪个 brain 方法；
真正不同的是每个方法收发的类型，全部换成 `schemas/communication/brain_tool_*.py`
里定义的这一跳专属 Req/Resp。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.communication import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToBrainToolReflectResp,
    FromHarnessToBrainToolVerifyAndSummarizeReq,
    FromHarnessToBrainToolVerifyAndSummarizeResp,
)


@runtime_checkable
class BrainToolPort(Protocol):
    """harness 认识的"大脑工具"——跟 `Brain` 之间的翻译门面。"""

    def choose_once(self, req: FromHarnessToBrainToolChooseOnceReq) -> FromHarnessToBrainToolChooseOnceResp:
        """转发一次决策尝试。失败：抛 `DecisionAttemptFailed`（同 `BrainPort`）。"""
        ...

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        """转发一次判定。永远返回 resp，不抛异常（同 `BrainPort`）。"""
        ...

    def reflect(self, req: FromHarnessToBrainToolReflectReq) -> FromHarnessToBrainToolReflectResp:
        """转发一次反思。"""
        ...

    def verify_and_summarize(self, req: FromHarnessToBrainToolVerifyAndSummarizeReq) -> FromHarnessToBrainToolVerifyAndSummarizeResp:
        """转发一次校验+蒸馏。永远返回 resp，不抛异常（同 `BrainPort`）。"""
        ...

    def plan_once(self, req: FromHarnessToBrainToolPlanOnceReq) -> FromHarnessToBrainToolPlanOnceResp:
        """转发一次 run 级规划尝试。失败：抛 `PlanAttemptFailed`（同 `BrainPort`）。"""
        ...
