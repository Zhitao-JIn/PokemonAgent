"""统一配置入口的用法：只覆盖指定字段，装配前拒绝不合法预算。"""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from pokemon_agent.config import DEFAULT_RUN_BUDGET
from pokemon_agent.run_config import load_run_config


def test_default_and_evaluation_share_all_layer_values(tmp_path):
    path = tmp_path / "run_config.json"
    overrides = {"wall_clock_s": 600, "max_episodes": 3, "max_total_actions": 60}
    path.write_text(json.dumps({"budget": overrides}), encoding="utf-8")

    production = load_run_config(None).budget
    evaluation = load_run_config(path).budget

    assert production.max_episodes == 10
    assert production.wall_clock_s is None and production.max_total_actions is None
    assert evaluation.model_dump() == {**production.model_dump(), **overrides}
    assert (production.reserve_s, production.episode_max_tasks, production.max_decompositions) == (
        60,
        6,
        2,
    )
    assert (production.task_max_steps, production.min_request_s) == (
        12,
        3,
    )
    assert (
        production.plan_thinking,
        production.plan_max_tokens,
        production.plan_timeout_s,
        production.brain_max_attempts,
    ) == (False, 4096, 45, 2)


def test_default_budget_max_episodes_is_ten() -> None:
    assert DEFAULT_RUN_BUDGET.max_episodes == load_run_config(None).budget.max_episodes == 10


@pytest.mark.parametrize(
    "data",
    [
        {"unknown": 1},
        {"budget": {"unknown": 1}},
        {"budget": {"max_episodes": "3"}},
        {"budget": {"max_episodes": True}},
        {"budget": {"task_max_steps": 0}},
        {"budget": {"task_default_steps": 8}},
        {"budget": {"wall_clock_s": 60}},
        {"budget": {"max_total_actions": 0}},
    ],
)
def test_invalid_configuration_is_rejected_before_assembly(tmp_path, data):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_run_config(path)


def test_empty_configuration_uses_defaults_and_a_missing_file_is_an_error(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("{}", encoding="utf-8")

    assert load_run_config(path).budget == DEFAULT_RUN_BUDGET
    with pytest.raises(FileNotFoundError):
        load_run_config(tmp_path / "missing.json")


def test_build_real_injects_the_budget_and_model_settings(tmp_path, monkeypatch):
    import pokemon_agent.build as assembly

    path = tmp_path / "run_config.json"
    path.write_text('{"budget":{"max_episodes":3}}', encoding="utf-8")
    brains = []
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

    def brain_build(**kwargs):
        brains.append(kwargs)
        return tools

    game, memory, trace = object(), object(), object()
    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    monkeypatch.setattr(assembly, "env_str", lambda name: "")
    monkeypatch.setattr(assembly.WorldMcpTool, "build", lambda *args, **kwargs: game)
    monkeypatch.setattr(assembly.MemoryTool, "build", lambda **kwargs: memory)
    monkeypatch.setattr(assembly.TraceTool, "build", lambda **kwargs: trace)
    monkeypatch.setattr(assembly.BrainTool, "build", brain_build)
    monkeypatch.setattr(assembly, "CHECKPOINT_ENABLED", False)
    monkeypatch.setattr(assembly, "build_saver", lambda root: None)
    monkeypatch.setattr(assembly, "compile_task_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_episode_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_run_graph", lambda **kwargs: None)

    monkeypatch.setattr(assembly, "assert_mcp_server_ready", lambda *args: {})

    harness, actual_game = assembly.build_real(
        config=path,
        trace_backend="local",
        memory_server_url="http://example",
        world_server_url="http://example",
    )

    assert actual_game is game
    assert harness.deps.budget.max_episodes == 3
    assert harness.deps.deadline is None
    assert all(
        b["plan_max_tokens"] == 4096
        and b["plan_thinking"] is False
        and b["plan_timeout_s"] == 45
        and b["max_attempts"] == 2
        for b in brains
    )


def test_brain_factory_uses_the_injected_plan_timeout(monkeypatch):
    import importlib

    from pokemon_agent.direct.brain_tool import BrainTool

    factory = importlib.import_module("pokemon_agent.brain.build_llm_providers")

    configurations = []

    def provider(model, **kwargs):
        configurations.append(kwargs)
        return object()

    monkeypatch.setattr(factory, "provider_for", provider)

    BrainTool.build(plan="deepseek-flash", plan_timeout_s=17)

    assert configurations[0]["timeout"] == 17
