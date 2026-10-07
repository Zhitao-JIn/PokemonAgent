"""独立成功判定集：真值目标、观测历史与人工标签。"""

import asyncio

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store_as
from pydantic import BaseModel

from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq


class JudgeCase(BaseModel):
    """标签不会传给判定器，只由 scorer 消费。"""

    case_id: str
    request: FromHarnessToBrainToolJudgeReq
    achieved: bool


class JudgeRecord(StoreModel):
    """模型判定与理由，供四格 scorer 读取。"""

    done: bool | None = None
    why: str = ""


@solver
def judge_solver(model: str) -> Solver:
    """生产 Judger 消费信封；网络或重试耗尽上抛为 sample error。"""
    judger = BrainTool.build(judge=model).judger

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case = JudgeCase.model_validate(state.metadata["case"])
        response = await asyncio.to_thread(judger.judge, case.request)
        record = store_as(JudgeRecord)
        record.done, record.why = response.done, response.why
        return state

    return solve
