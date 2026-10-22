"""Frozen replay envelopes and explicit gateway conversion; no baseline generation."""

from typing import Literal

from pydantic import BaseModel, JsonValue

from evals.common.legacy_requests.registry import REQUESTS as LEGACY
from pokemon_agent.direct.brain_tool import decide_prompt_params
from pokemon_agent.prompt import (
    DecideActionParams,
    DecideActionRetryParams,
    DecomposeParams,
    JudgeParams,
    PromptGateway,
    RunPlanParams,
    SummarizeParams,
    SummarizeRunParams,
    SummarizeTaskParams,
    VerifyParams,
)
from pokemon_agent.schemas import harness as h
from pokemon_agent.world import TERRAIN_MEANING

from .legacy_adapter import adapt_request

CURRENT: dict[str, type[BaseModel]] = {
    "choose": h.FromHarnessToBrainToolChooseOnceReq,
    "judge": h.FromHarnessToBrainToolJudgeReq,
    "decompose": h.FromHarnessToBrainToolDecomposeReq,
    "plan": h.FromHarnessToBrainToolPlanOnceReq,
    "summarize": h.FromHarnessToBrainToolSummarizeReq,
    "summarize_task": h.FromHarnessToBrainToolSummarizeTaskReq,
    "summarize_run": h.FromHarnessToBrainToolSummarizeRunReq,
    "verify": h.FromHarnessToBrainToolVerifyReq,
}
METHODS = {
    "decide_action": "choose",
    "judge_success": "judge",
    "decompose": "decompose",
    "run_plan": "plan",
    "summarize": "summarize",
    "summarize_task": "summarize_task",
    "summarize_run": "summarize_run",
    "verify": "verify",
}
CONTRACTS: dict[str, type[BaseModel]] = {
    "decide_action": DecideActionParams,
    "judge_success": JudgeParams,
    "decompose": DecomposeParams,
    "run_plan": RunPlanParams,
    "verify": VerifyParams,
    "summarize": SummarizeParams,
    "summarize_task": SummarizeTaskParams,
    "summarize_run": SummarizeRunParams,
}


class GoldenCase(BaseModel):
    """Captured original request and provenance, without rewriting stored inputs."""

    task: str
    case_id: str
    source: Literal["history", "synthetic", "act_memory"]
    request_kind: Literal["current", "legacy", "retry"] = "current"
    request: dict[str, JsonValue]
    max_segments: int = 3
    source_ref: str = ""


def parse_request(case: GoldenCase) -> BaseModel:
    """Validate the recorded current or frozen envelope without inventing fields."""
    method = METHODS[case.task]
    cls = LEGACY[method] if case.request_kind == "legacy" else CURRENT[method]
    return cls.model_validate(case.request)


def render_case(case: GoldenCase, gateway: PromptGateway) -> bytes:
    """Render through the active registry; unrecoverable input remains an explicit error."""
    if case.task == "retry_prompt":
        params = DecideActionRetryParams.model_validate(case.request)
        return gateway.render("decide_action_retry", params).text.encode("utf-8")
    adapted = adapt_request(case.request)
    req = parse_request(case.model_copy(update={"request": adapted.request}))
    data = req.model_dump(mode="json")
    if case.task in {"summarize", "summarize_task"}:
        data["success"] = req.success
    if case.task == "decompose":
        data["terrain_meanings"] = TERRAIN_MEANING
    params = (
        decide_prompt_params(req, max_segments=case.max_segments)
        if case.task == "decide_action"
        else CONTRACTS[case.task].model_validate(data)
    )
    if adapted.prompt_fields:
        params = CONTRACTS[case.task].model_validate(
            {**params.model_dump(mode="json"), **adapted.prompt_fields}
        )
    return gateway.render(case.task, params).text.encode("utf-8")
