"""Inspect 调用生产 chooser；旁账参考不进入生成器的原始请求。"""

import asyncio

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from evals.common.brain_link import single_link_brain
from pokemon_agent.brain.interface import Action
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import ModelCall

from .dataset import Case


class Record(StoreModel):
    """单个样本的候选动作和尝试账；异常也保留其失败理由。"""

    answer: Action | None = None
    calls: list[ModelCall] = Field(default_factory=list)
    failure: str = ""


@solver
def choose_solver(model: str) -> Solver:
    """仅发送原始信封；解析或提供者耗尽为 Inspect sample error，不伪造评分。"""
    port = single_link_brain("text", model).chooser

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case, record = Case.model_validate(state.metadata["case"]), store_as(Record)
        try:
            response = await asyncio.to_thread(port.choose, case.request)
        except MaxRetriesExceeded as error:
            record.calls, record.failure = list(error.calls), str(error)
            raise
        record.answer, record.calls = response.action, response.calls
        state.output.completion = record.answer.model_dump_json()
        return state

    return solve
