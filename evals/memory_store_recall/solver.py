"""真实记忆存储与检索 solver，运行记录供 scorer 读取。"""

from pathlib import Path

from pydantic import BaseModel, Field

from evals.common.memory_server import clear_memory
from pokemon_agent.direct.interface.ports import MemoryToolPort
from pokemon_agent.env import env_str, load_env_file
from pokemon_agent.mcpclient import McpTransportError, assert_mcp_server_ready
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
)

from .dataset import MemoryDataset


class MemoryRun(BaseModel):
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


def run_memory(dataset: MemoryDataset, k: int) -> MemoryRun:
    """先清空评测专用共享 server 再评测；真实本地 embedding 与 reranker。"""
    load_env_file()
    url = env_str("MCP_MEMORY_SERVER_URL")
    if not url:
        raise McpTransportError(
            "memory 只经 MCP：设 MCP_MEMORY_SERVER_URL 或传 memory_server_url，并先起 memory server"
        )
    health = assert_mcp_server_ready(url, "memory")
    if health.get("admin") is not True:
        raise McpTransportError("评测需要带 --enable-admin 的专用 memory server")
    root_directory = Path.cwd() / "eval_results"
    root_directory.mkdir(exist_ok=True)
    tool = MemoryTool.build(memory_server_url=url, memory_root=root_directory)
    clear_memory(tool)
    return evaluate_memory(dataset, tool, k)
