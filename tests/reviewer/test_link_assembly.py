"""真实装配入口选择复核实现，并把同一实例与 trace.flush 接给三层运行时。"""

from types import SimpleNamespace

import pytest

from pokemon_agent import build as assembly
from pokemon_agent.harness.null_reviewer import NullReviewer


@pytest.fixture
def assembled(tmp_path, monkeypatch):
    flushes, connections = [], []
    trace = SimpleNamespace(flush=lambda: flushes.append(1))
    tools = SimpleNamespace(
        **{
            name: object()
            for name in (
                "chooser",
                "judger",
                "planner",
                "reflector",
                "verifier",
                "decomposer",
                "summarizer",
                "run_summarizer",
                "task_summarizer",
            )
        }
    )
    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    monkeypatch.setattr(assembly.WorldMcpTool, "build", lambda *args, **kwargs: object())
    monkeypatch.setattr(assembly.MemoryTool, "build", lambda **kwargs: object())
    monkeypatch.setattr(assembly.TraceTool, "build", lambda **kwargs: trace)
    monkeypatch.setattr(assembly.BrainTool, "build", lambda **kwargs: tools)
    monkeypatch.setattr(assembly, "CHECKPOINT_ENABLED", False)
    monkeypatch.setattr(assembly, "build_saver", lambda root: None)
    monkeypatch.setattr(assembly, "compile_task_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_episode_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_run_graph", lambda **kwargs: None)
    monkeypatch.setattr(assembly, "assert_mcp_server_ready", lambda *args: {})
    monkeypatch.setattr(assembly, "REVIEW_LINK_URL", None)

    def remote(url, *, flush, lost_timeout_s):
        reviewer = NullReviewer()
        connections.append((url, flush, lost_timeout_s, reviewer))
        return reviewer

    monkeypatch.setattr(assembly, "RemoteReviewer", remote)
    return flushes, connections


@pytest.mark.parametrize(
    "explicit, environment, injected",
    [
        ("ws://explicit", "ws://environment", False),
        (None, "ws://environment", False),
        (None, None, False),
        ("ws://explicit", "ws://environment", True),
    ],
)
def test_build_real_uses_explicit_url_then_environment_and_keeps_injected_reviewer_priority(
    assembled, monkeypatch, explicit, environment, injected
) -> None:
    flushes, connections = assembled
    monkeypatch.setattr(
        assembly, "env_str", lambda name: environment if name == "REVIEW_LINK_URL" else None
    )
    reviewer = NullReviewer() if injected else None

    harness, _ = assembly.build_real(
        reviewer=reviewer,
        reviewer_url=explicit,
        memory_server_url="http://example",
        world_server_url="http://example",
        trace_backend="local",
    )

    selected = harness.deps.reviewer
    assert harness.deps.episode.reviewer is selected
    assert harness.deps.episode.task.reviewer is selected
    if injected:
        assert selected is reviewer and not connections
    elif explicit or environment:
        url, flush, budget, remote = connections[0]
        assert url == (explicit or environment) and selected is remote
        assert budget == assembly.REVIEW_LINK_LOST_TIMEOUT_S
        flush()
        assert flushes == [1]
    else:
        assert isinstance(selected, NullReviewer) and not connections
