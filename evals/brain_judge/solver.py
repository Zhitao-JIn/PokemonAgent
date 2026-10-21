"""生产目标判定 solver 与交接记录，真值由独立数据集提供。"""

import asyncio

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from evals.dataset.brain_judge import JudgeCase
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq, ModelCall


class JudgeRecord(StoreModel):
    """模型判定与理由，供四格 scorer 读取。"""

    done: bool | None = None
    decision: str | None = None
    why: str = ""
    calls: list[ModelCall] = Field(default_factory=list)
    failure: str = ""


@solver
def judge_solver(model: str) -> Solver:
    """生产 Judger 消费信封；网络或重试耗尽上抛为 sample error。"""
    judger = BrainTool.build(judge=model).judger

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case = JudgeCase.model_validate(state.metadata["case"])
        if not isinstance(case.request, FromHarnessToBrainToolJudgeReq):
            raise ValueError("旧任务表缺少新契约素材，仅供审计；请选择重采版本")
        record = store_as(JudgeRecord)
        try:
            response = await asyncio.to_thread(judger.judge, case.request)
        except MaxRetriesExceeded as exc:
            record.calls, record.failure = list(exc.calls), str(exc)
            raise
        record.calls, record.decision = response.calls, response.decision
        state.output.completion = response.model_dump_json(exclude={"calls"})
        record.done, record.why = response.done, response.why
        return state

    return solve
