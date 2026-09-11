"""`BrainToolPort` 的唯一实现：harness 和 `Brain` 之间那层翻译壳。

持有一个 `BrainPort`（真正的大脑）。每个方法做同一件事：把 harness 给的
`BrainTool*Req` 翻译成 `Brain` 认识的原生 Req，调对应的 `Brain` 方法，
再把原生 Resp 翻译回 `BrainTool*Resp`。**今天的翻译逐字段原样对应**——
两套契约字段目前重合，但类型故意不共用，以后任一边单独变形状都不用
牵动另一边。异常（`DecisionAttemptFailed`/`PlanAttemptFailed`）原样穿透，
不在这里包一层新异常——两跳共享同一套"这次尝试失败"的语义。
"""

from __future__ import annotations

from pokemon_agent.brain import BrainPort
from pokemon_agent.schemas.brain import (
    ChooseOnceReq,
    JudgeReq,
    PlanOnceReq,
    ReflectReq,
    VerifyAndSummarizeReq,
)
from pokemon_agent.schemas.harness import (
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


class BrainTool:
    """`BrainToolPort` 的唯一实现。持有真正的 `Brain`（或任何 `BrainPort` 实现）。"""

    def __init__(self, brain: BrainPort) -> None:
        """接好大脑。**本对象没有状态**，纯转发+翻译。"""
        self._brain = brain

    def choose_once(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        """决策：翻译 req → 调 `Brain.choose_once()` → 翻译 resp。"""
        resp = self._brain.choose_once(ChooseOnceReq(**req.model_dump()))
        return FromHarnessToBrainToolChooseOnceResp(**resp.model_dump())

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        """判定：翻译 req → 调 `Brain.judge()` → 翻译 resp。"""
        resp = self._brain.judge(JudgeReq(**req.model_dump()))
        return FromHarnessToBrainToolJudgeResp(**resp.model_dump())

    def reflect(self, req: FromHarnessToBrainToolReflectReq) -> FromHarnessToBrainToolReflectResp:
        """反思：翻译 req → 调 `Brain.reflect()` → 取 `entry` 包成
        `FromHarnessToBrainToolReflectResp`。"""
        resp = self._brain.reflect(ReflectReq(**req.model_dump()))
        return FromHarnessToBrainToolReflectResp(entry=resp.entry)

    def verify_and_summarize(
        self, req: FromHarnessToBrainToolVerifyAndSummarizeReq
    ) -> FromHarnessToBrainToolVerifyAndSummarizeResp:
        """校验+蒸馏：翻译 req → 调 `Brain.verify_and_summarize()` → 翻译 resp。"""
        resp = self._brain.verify_and_summarize(VerifyAndSummarizeReq(**req.model_dump()))
        return FromHarnessToBrainToolVerifyAndSummarizeResp(**resp.model_dump())

    def plan_once(
        self, req: FromHarnessToBrainToolPlanOnceReq
    ) -> FromHarnessToBrainToolPlanOnceResp:
        """run 级规划：翻译 req → 调 `Brain.plan_once()` → 翻译 resp。"""
        resp = self._brain.plan_once(PlanOnceReq(**req.model_dump()))
        return FromHarnessToBrainToolPlanOnceResp(**resp.model_dump())
