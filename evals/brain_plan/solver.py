"""只调用生产 planner，保存解析结果和真实模型尝试供审计。"""

import asyncio

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from evals.common.brain_link import single_link_brain
from pokemon_agent.brain.interface import RunPlan
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq, ModelCall

from .dataset import Case


class Record(StoreModel):
    """单个 plan 的返回值；无跨样本状态。"""

    answer: RunPlan | None = None
    calls: list[ModelCall] = Field(default_factory=list)
    failure: str = ""


@solver
def plan_solver(model: str) -> Solver:
    """仅传完整原始信封；提供者或重试耗尽保留为 Inspect sample error。"""
    port = single_link_brain("plan", model).planner

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case = Case.model_validate(state.metadata["case"])
        if case.contract_version != "v2" or not isinstance(
            case.request, FromHarnessToBrainToolPlanOnceReq
        ):
            raise ValueError("旧版本仅供审计；新规划契约需要完整新请求，请选择重采版本")
        record = store_as(Record)
        try:
            response = await asyncio.to_thread(port.plan, case.request)
        except MaxRetriesExceeded as error:
            record.calls, record.failure = list(error.calls), str(error)
            raise
        record.answer, record.calls = response.plan, response.calls
        state.output.completion = record.answer.model_dump_json()
        return state

    return solve
