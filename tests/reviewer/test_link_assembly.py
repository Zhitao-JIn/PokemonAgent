"""`ReviewerTool.build` 按 `review.mode` 选择复核实现；`build_real` 把同一实例交给三层运行时。"""

import json
from types import SimpleNamespace

import pytest
from _harness_fixtures.app_config import app_config

from pokemon_agent import build as assembly
from pokemon_agent.direct import reviewer_tool
from pokemon_agent.direct.reviewer_tool import ReviewerTool
from pokemon_agent.harness.null_reviewer import NullReviewer


@pytest.fixture
def connections(monkeypatch):
    seen = []

    def remote(url, *, flush, lost_timeout_s):
        client = NullReviewer()
        seen.append((url, flush, lost_timeout_s, client))
        return client

    monkeypatch.setattr(reviewer_tool, "RemoteReviewer", remote)
    return seen


def test_off_mode_is_headless_and_never_connects(connections) -> None:
    review = app_config(review={"mode": "off"}).review

    reviewer = ReviewerTool.build(review, flush=lambda: None)

    assert isinstance(reviewer, NullReviewer) and not connections


@pytest.mark.parametrize("mode", ["human", "ai", "both"])
def test_any_other_mode_connects_to_the_configured_link(connections, mode) -> None:
    review = app_config(review={"mode": mode, "link_url": "ws://127.0.0.1:9"}).review
    flushes = []

    reviewer = ReviewerTool.build(review, flush=lambda: flushes.append(1))

    url, flush, lost_timeout_s, client = connections[0]
    assert reviewer is client and url == "ws://127.0.0.1:9"
    assert lost_timeout_s == review.link_lost_timeout_s
    flush()
    assert flushes == [1]


def test_build_real_hands_the_same_reviewer_to_all_three_layers(
    tmp_path, monkeypatch, connections
) -> None:
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps(
            {
                "review": {"mode": "human", "link_url": "ws://127.0.0.1:9"},
                "paths": {"runs_root": str(tmp_path)},
                "services": {"world_server_url": "http://w", "memory_server_url": "http://m"},
                "checkpoint": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    trace = SimpleNamespace(flush=lambda: None)
    tools = SimpleNamespace(**dict.fromkeys(_TOOL_NAMES, object()))
    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    monkeypatch.setattr(assembly.WorldMcpTool, "build", lambda *args, **kwargs: object())
    monkeypatch.setattr(assembly.MemoryTool, "build", lambda **kwargs: object())
    monkeypatch.setattr(assembly.TraceTool, "build", lambda **kwargs: trace)
    monkeypatch.setattr(assembly.BrainTool, "build", lambda **kwargs: tools)
    monkeypatch.setattr(assembly, "compile_task_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_episode_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_run_graph", lambda: None)
    monkeypatch.setattr(assembly, "assert_mcp_server_ready", lambda *args: {})

    harness, _ = assembly.build_real(overlay)

    selected = harness.deps.reviewer
    assert connections[0][3] is selected
    assert harness.deps.episode.reviewer is selected
    assert harness.deps.episode.task.reviewer is selected


_TOOL_NAMES = (
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
