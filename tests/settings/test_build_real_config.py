"""`build_real` 只收配置文件：预算、型号、重试等全部由配置注入，无显式参数。"""

import inspect
import json
from types import SimpleNamespace

import pytest

from pokemon_agent import build as assembly
from pokemon_agent.mcpclient.client import McpTransportError

_TOOLS = (
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


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    brains, traces, snapshots = [], [], []
    tools = SimpleNamespace(**dict.fromkeys(_TOOLS, object()))

    def brain_build(**kwargs):
        brains.append(kwargs)
        return tools

    def trace_build(**kwargs):
        traces.append(kwargs)
        return SimpleNamespace(flush=lambda: None)

    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    monkeypatch.setattr(assembly.WorldMcpTool, "build", lambda *args, **kwargs: object())
    monkeypatch.setattr(assembly.MemoryTool, "build", lambda **kwargs: object())
    monkeypatch.setattr(assembly.TraceTool, "build", trace_build)
    monkeypatch.setattr(assembly.BrainTool, "build", brain_build)
    monkeypatch.setattr(assembly, "build_saver", lambda root: None)
    monkeypatch.setattr(assembly, "compile_task_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_episode_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_run_graph", lambda **kwargs: None)
    monkeypatch.setattr(assembly, "assert_mcp_server_ready", lambda *args: {})
    real_snapshot = assembly.write_snapshot
    monkeypatch.setattr(
        assembly, "write_snapshot", lambda *args: snapshots.append(real_snapshot(*args))
    )

    def overlay(**extra):
        data = {
            "paths": {"runs_root": str(tmp_path)},
            "services": {"world_server_url": "http://w", "memory_server_url": "http://m"},
            "checkpoint": {"enabled": False},
            **extra,
        }
        path = tmp_path / "overlay.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return SimpleNamespace(brains=brains, traces=traces, snapshots=snapshots, overlay=overlay)


def test_build_real_takes_nothing_but_configuration_paths() -> None:
    assert list(inspect.signature(assembly.build_real).parameters) == ["config"]


def test_the_effective_configuration_reaches_every_runtime(stubbed) -> None:
    harness, _ = assembly.build_real(stubbed.overlay(budget={"max_episodes": 3}))

    for runtime in (harness.deps, harness.deps.episode, harness.deps.episode.task):
        assert runtime.config.budget.max_episodes == 3
    assert harness.deps.deadline is None


def test_each_layer_builds_its_own_brain_from_the_configured_models(stubbed) -> None:
    assembly.build_real(stubbed.overlay(models={"plan": {"model": "deepseek-flash"}}))

    assert [kwargs["links"] for kwargs in stubbed.brains] == [
        ("plan", "judge"),
        ("plan", "judge", "verify"),
        ("text", "judge", "verify"),
    ]
    assert all(kwargs["models"].plan.model == "deepseek-flash" for kwargs in stubbed.brains)
    assert all(kwargs["retry"].brain_max_attempts == 2 for kwargs in stubbed.brains)


def test_trace_follows_the_configured_backend_and_run_identity(stubbed, tmp_path) -> None:
    assembly.build_real(stubbed.overlay(run={"run_id": "exp-1", "branch": "b"}))

    request = stubbed.traces[0]
    assert (request["run_id"], request["branch"], request["backend"]) == ("exp-1", "b", "local")
    assert request["trace_root"] == tmp_path / "tracelog"


def test_a_wall_clock_budget_creates_the_run_deadline(stubbed) -> None:
    harness, _ = assembly.build_real(stubbed.overlay(budget={"wall_clock_s": 600}))

    assert harness.deps.deadline is not None


def test_the_effective_configuration_is_snapshotted_for_the_run(stubbed, tmp_path) -> None:
    assembly.build_real(stubbed.overlay(run={"run_id": "snap"}))

    [path] = stubbed.snapshots
    assert path.parent == tmp_path / "config_snapshots" and path.name.startswith("snap-")


@pytest.mark.parametrize("missing", ["world_server_url", "memory_server_url"])
def test_a_missing_service_address_fails_at_assembly(stubbed, missing) -> None:
    services = {"world_server_url": "http://w", "memory_server_url": "http://m", missing: None}

    with pytest.raises(McpTransportError):
        assembly.build_real(stubbed.overlay(services=services))
