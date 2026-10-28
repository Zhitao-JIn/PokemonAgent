"""Captured request envelopes and active-version prompt stamps."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, JsonValue

from evals.common.legacy_requests.registry import REQUESTS as LEGACY
from pokemon_agent.prompt import (
    DecideActionParams,
    DecomposeParams,
    JudgeParams,
    RunPlanParams,
    SummarizeParams,
    SummarizeRunParams,
    SummarizeTaskParams,
    VerifyParams,
)
from pokemon_agent.schemas import harness as h

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


PACKAGED_REGISTRY = (
    Path(__file__).resolve().parents[2] / "pokemon_agent" / "prompt" / "registry.json"
)


def active_version(task: str) -> str:
    """注册表里该任务当前生效的版本——盖章断言不写死版本号。"""
    data = json.loads(PACKAGED_REGISTRY.read_text(encoding="utf-8"))
    return data["tasks"][task]["active"]
