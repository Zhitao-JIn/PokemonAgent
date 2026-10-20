"""新 reviewer 的进程内请求样本；只构造公开模型，不调用真实依赖。"""

from _review_context import review_context

from _doubles.memory_server import act
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerInjectReq,
    ModelCall,
)
from pokemon_agent.schemas.memory import ActMemory


def inject_request(*, frames: bool = False) -> FromHarnessToReviewerInjectReq:
    """插话素材可携带三张不重复的历史帧。"""
    ctx = review_context()
    if frames:
        first, second = act(1)["payload"], act(2)["payload"]
        first.update(
            before_frame="data:image/png;base64,YQ==", after_frame="data:image/png;base64,Yg=="
        )
        second.update(
            before_frame="data:image/png;base64,Yg==", after_frame="data:image/png;base64,Yw=="
        )
        ctx.brain_input.history = [
            ActMemory.model_validate(first),
            ActMemory.model_validate(second),
        ]
    return FromHarnessToReviewerInjectReq(context=ctx, prompt="请看提案", form={"goal": "next"})


def audit_request() -> FromHarnessToReviewerAuditReq:
    """已达成结论的审问。"""
    return FromHarnessToReviewerAuditReq(
        context=review_context(),
        run_id="r1",
        episode_id="r1-ep1",
        outcome=FromHarnessToBrainToolJudgeResp(done=True, why="达成", calls=[ModelCall()]),
    )
