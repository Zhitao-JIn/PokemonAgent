"""真实记忆存储与检索 solver，运行记录供 scorer 读取。"""

import asyncio
import tempfile
from pathlib import Path

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from evals.dataset.memory_store_recall import MemoryDataset
from pokemon_agent.direct.interface.ports import MemoryToolPort
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
)


class MemoryRun(StoreModel):
    """一次写入、逐条读回、全部检索的交接面。"""

    storage_problems: list[str] = Field(default_factory=list)
    retrieved: dict[str, list[str]] = Field(default_factory=dict)


def evaluate_memory(dataset: MemoryDataset, tool: MemoryToolPort, k: int) -> MemoryRun:
    """先写后读；uuid 映射来自写入响应；检索与存储使用同一库。"""
    result = MemoryRun()
    identities: dict[str, str] = {}
    for entry in dataset.records:
        response = tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[entry.record]))
        if len(response.stored) != 1:
            result.storage_problems.append(f"{entry.record_id}: 未落库")
            continue
        uuid = response.stored[0].uuid
        identities[uuid] = entry.record_id
        recalled = tool.recall(
            FromHarnessToMemoryToolRecallReq(
                query=entry.query, conditions=entry.conditions, limit=len(dataset.records)
            )
        )
        item = next((item for item in recalled.items if item.uuid == uuid), None)
        if item is None or item.content != entry.expected_content:
            result.storage_problems.append(f"{entry.record_id}: 读回正文不符")
        if (
            item is not None
            and entry.record.kind != "knowledge"
            and any(item.payload.get(key) != value for key, value in entry.record.payload.items())
        ):
            result.storage_problems.append(f"{entry.record_id}: 读回结构不符")
    for query in dataset.queries:
        recalled = tool.recall(
            FromHarnessToMemoryToolRecallReq(query=query.text, conditions=query.conditions, limit=k)
        )
        result.retrieved[query.query_id] = [
            identities.get(item.uuid, "") for item in recalled.items
        ]
    return result


@solver
def memory_solver(k: int) -> Solver:
    """每样本一个隔离库，真实本地 embedding 与 reranker。"""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        dataset = MemoryDataset.model_validate(state.metadata["dataset"])
        with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=".eval-memory-") as root:
            tool = MemoryTool.build(memory_root=root, max_summaries=len(dataset.records))
            result = await asyncio.to_thread(evaluate_memory, dataset, tool, k)
            record = store_as(MemoryRun)
            record.storage_problems, record.retrieved = result.storage_problems, result.retrieved
        return state

    return solve
