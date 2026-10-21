"""只调用生产 decomposer，保存解析结果和真实模型尝试供审计。"""

import asyncio

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import FromHarnessToBrainToolDecomposeReq, ModelCall

from .dataset import Case


class Record(StoreModel):
    """单个 decompose 的返回值；无跨样本状态。"""

    answer: Decomposition | None = None
    calls: list[ModelCall] = Field(default_factory=list)
    failure: str = ""


@solver
def decompose_solver(model: str) -> Solver:
    """仅传完整原始信封；提供者或重试耗尽保留为 Inspect sample error。"""
    port = BrainTool.build(plan=model).decomposer

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case = Case.model_validate(state.metadata["case"])
        if case.contract_version != "v2" or not isinstance(
            case.request, FromHarnessToBrainToolDecomposeReq
        ):
            raise ValueError("旧版本仅供审计；新规划契约需要完整新请求，请选择重采版本")
        record = store_as(Record)
        try:
            response = await asyncio.to_thread(port.decompose, case.request)
        except MaxRetriesExceeded as error:
            record.calls, record.failure = list(error.calls), str(error)
            raise
        record.answer, record.calls = response.decomposition, response.calls
        state.output.completion = record.answer.model_dump_json()
        return state

    return solve
