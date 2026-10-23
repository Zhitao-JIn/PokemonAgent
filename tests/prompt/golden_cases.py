"""Frozen replay envelopes and explicit gateway conversion; no baseline generation."""

import json
from pathlib import Path
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


def params_for(case: GoldenCase) -> BaseModel:
    """历史兼容只读原始JSON，保留被新信封忽略的旧值，不补造语义。"""
    adapted = adapt_request(case.request)
    req = parse_request(case.model_copy(update={"request": adapted.request}))
    data = req.model_dump(mode="json")
    if case.task in {"summarize", "summarize_task"}:
        data["success"] = req.success
    data.update(adapted.request)
    if case.task == "decompose":
        data["terrain_meanings"] = TERRAIN_MEANING
    if case.task == "decide_action":
        converted = decide_prompt_params(req, max_segments=case.max_segments).model_dump(
            mode="json"
        )
        observation = {**converted["observation"], **adapted.request["obs"]}
        converted.update(
            {key: value for key, value in adapted.request.items() if key not in {"obs", "space"}}
        )
        converted["observation"] = observation
        data = converted
    data.update(adapted.prompt_fields)
    return CONTRACTS[case.task].model_validate(data)


def render_case(case: GoldenCase, gateway: PromptGateway) -> bytes:
    """只经活动网关对冻结文本，不写入golden。"""
    if case.task == "retry_prompt":
        return gateway.render(
            "decide_action_retry", DecideActionRetryParams.model_validate(case.request)
        ).text.encode("utf-8")
    return gateway.render(case.task, params_for(case)).text.encode("utf-8")


PACKAGED_REGISTRY = (
    Path(__file__).resolve().parents[2] / "pokemon_agent" / "prompt" / "registry.json"
)


def frozen_v1_registry(root: Path) -> Path:
    """把每个单元钉在 v1：golden 由 v1 渲染，活动版本升到 v2 后这份基线仍要能逐字节复现。"""
    data = json.loads(PACKAGED_REGISTRY.read_text(encoding="utf-8"))
    pinned = {name: {"active": "v1"} for name in data["tasks"]}
    path = root / "frozen-v1-registry.json"
    path.write_text(json.dumps({"tasks": pinned}), encoding="utf-8")
    return path


def active_version(task: str) -> str:
    """注册表里该任务当前生效的版本——盖章断言不写死版本号。"""
    data = json.loads(PACKAGED_REGISTRY.read_text(encoding="utf-8"))
    return data["tasks"][task]["active"]
