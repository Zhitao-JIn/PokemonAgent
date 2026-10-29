"""run_memory 只使用隔离的临时 MCP memory 服务。"""

from __future__ import annotations

from contextlib import contextmanager

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


def _install_fake_services(monkeypatch: pytest.MonkeyPatch, events: list) -> None:
    @contextmanager
    def fake_services(**options):
        events.append(("enter", options))
        try:
            yield {"MCP_MEMORY_SERVER_URL": "http://memory.fake"}
        finally:
            events.append(("exit",))

    monkeypatch.setattr(solver, "eval_services", fake_services)


def test_run_memory_requires_memory_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺 MCP_MEMORY_SERVER_URL → McpTransportError（文案含变量名）。"""
    events = []
    monkeypatch.setattr(solver, "load_env_file", lambda: None)
    monkeypatch.setattr(solver, "env_str", lambda name: None)
    _install_fake_services(monkeypatch, events)

    with pytest.raises(McpTransportError, match="MCP_MEMORY_SERVER_URL"):
        solver.run_memory(_dataset(), k=1)
    assert [event[0] for event in events] == ["enter", "exit"]


def test_run_memory_rejects_an_external_memory_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """已有 MCP_MEMORY_SERVER_URL 时拒绝复用，避免触碰共享记忆库。"""
    events = []
    monkeypatch.setenv("MCP_MEMORY_SERVER_URL", "http://memory.shared")
    monkeypatch.setattr(solver, "load_env_file", lambda: None)
    _install_fake_services(monkeypatch, events)

    with pytest.raises(
        McpTransportError, match="评测必须使用隔离的临时 memory 服务，请清除 MCP_MEMORY_SERVER_URL"
    ):
        solver.run_memory(_dataset(), k=1)
    assert events == []


def test_run_memory_runs_inside_an_isolated_temporary_service_without_clearing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = []
    tool = object()
    monkeypatch.setattr(solver, "load_env_file", lambda: None)
    memory_urls = iter([None, "http://memory.fake"])
    monkeypatch.setattr(solver, "env_str", lambda name: next(memory_urls))
    monkeypatch.setattr(solver, "assert_mcp_server_ready", lambda url, service: {})
    monkeypatch.setattr(solver.MemoryTool, "build", lambda **kwargs: tool)
    monkeypatch.setattr(
        solver,
        "evaluate_memory",
        lambda dataset, received, k: events.append(("evaluate", received)),
    )
    _install_fake_services(monkeypatch, events)
    monkeypatch.chdir(tmp_path)

    result = solver.run_memory(_dataset(), k=3)

    assert result is None
    assert events == [
        (
            "enter",
            {"world": False, "memory": True, "knowledge_source": None},
        ),
        ("evaluate", tool),
        ("exit",),
    ]
