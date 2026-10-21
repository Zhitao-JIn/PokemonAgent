"""精确信封调用生产蒸馏门面，保留候选正文与真实发送账。"""

import asyncio

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeResp,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeRunResp,
    FromHarnessToBrainToolSummarizeTaskReq,
    FromHarnessToBrainToolSummarizeTaskResp,
    ModelCall,
)

from .contract import SummaryAnswer, SummaryRequest
from .dataset import Case


class Record(StoreModel):
    """每个样本独立的解析正文和调用账；不保存门面盖的来源章。"""

    answer: SummaryAnswer | None = None
    calls: list[ModelCall] = Field(default_factory=list)
    failure: str = ""


def invoke(
    tools: BrainTool, request: SummaryRequest
) -> (
    FromHarnessToBrainToolSummarizeTaskResp
    | FromHarnessToBrainToolSummarizeResp
    | FromHarnessToBrainToolSummarizeRunResp
):
    """按精确请求类型选生产端口；类型由 dataset 保证。"""
    if isinstance(request, FromHarnessToBrainToolSummarizeTaskReq):
        return tools.task_summarizer.summarize_task(request)
    if isinstance(request, FromHarnessToBrainToolSummarizeRunReq):
        return tools.run_summarizer.summarize_run(request)
    return tools.summarizer.summarize(request)


@solver
def summary_solver(model: str) -> Solver:
    """复用生产 verify provider；失败保留账并作为 Inspect sample error 上抛。"""
    tools = BrainTool.build(verify=model)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case, record = Case.model_validate(state.metadata["case"]), store_as(Record)
        try:
            response = await asyncio.to_thread(invoke, tools, case.request)
        except MaxRetriesExceeded as error:
            record.calls, record.failure = list(error.calls), str(error)
            raise
        record.answer, record.calls = response.summary, response.calls
        state.output.completion = record.answer.model_dump_json()
        return state

    return solve
