"""run_memory 改走 MCP：缺地址与缺 admin 都明确失败。"""

from __future__ import annotations

import pytest

from evals.memory_store_recall import solver
from evals.memory_store_recall.dataset import FrozenRecord, MemoryDataset, Query
from pokemon_agent.mcpclient import McpTransportError
from pokemon_agent.schemas.harness import FromHarnessToMemoryToolMemorizeRecord


def _dataset() -> MemoryDataset:
    return MemoryDataset(
        records=[
            FrozenRecord(
                record_id="r1",
                record=FromHarnessToMemoryToolMemorizeRecord(
                    kind="knowledge", payload={"topic": "t", "content": "c", "source": "s"}
                ),
                query="q",
                expected_content="c",
            )
        ],
        queries=[Query(query_id="q1", text="t", relevant=["r1"])],
    )


def test_run_memory_requires_memory_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺 MCP_MEMORY_SERVER_URL → McpTransportError（文案含变量名）。"""
    monkeypatch.setattr(solver, "load_env_file", lambda: None)
    monkeypatch.setattr(solver, "env_str", lambda name: None)

    with pytest.raises(McpTransportError, match="MCP_MEMORY_SERVER_URL"):
        solver.run_memory(_dataset(), k=1)


def test_run_memory_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """health 的 admin 非 True → McpTransportError。"""
    monkeypatch.setattr(solver, "load_env_file", lambda: None)
    monkeypatch.setattr(solver, "env_str", lambda name: "http://fake")
    monkeypatch.setattr(solver, "assert_mcp_server_ready", lambda url, service: {"admin": False})

    with pytest.raises(McpTransportError, match="--enable-admin"):
        solver.run_memory(_dataset(), k=1)
