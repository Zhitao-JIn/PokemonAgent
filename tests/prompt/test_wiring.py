"""Empty-registry construction and raw configuration wiring do not call any model."""

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.settings import load_config
from pokemon_agent.settings.schema import PromptSection

from .unit_fixtures import ExampleParams, make_registry, make_unit

ROOT = Path(__file__).resolve().parents[2]


def build_tool(registry: str | None = None) -> BrainTool:
    app = load_config().config
    return BrainTool.build(
        links=(),
        models=app.models,
        retry=app.retry,
        request_timeouts=app.request_timeouts_s,
        action_limits=app.action_limits,
        image_cap=app.memory.scope_image_cap,
        prompt_registry=registry,
    )


def test_prompt_configuration_has_exactly_one_required_nullable_field(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.json"
    overlay.write_bytes(json.dumps({"prompt": {"registry": "fixtures/registry.json"}}).encode())

    defaults = load_config().config
    overridden = load_config(overlay).config

    assert set(PromptSection.model_fields) == {"registry"}
    assert PromptSection.model_fields["registry"].is_required()
    assert defaults.prompt.registry is None
    assert overridden.prompt.registry == "fixtures/registry.json"
    with pytest.raises(ValidationError):
        PromptSection(registry=None, version="v1")


def test_the_factory_injects_one_gateway_into_all_eight_model_capabilities() -> None:
    """八个调模型的能力共用同一个网关；`Reflector` 不调模型，不持网关（决定 D）。"""
    tool = build_tool()

    capabilities = [value for value in vars(tool).values() if hasattr(value, "_prompt_gateway")]
    gateways = [capability._prompt_gateway for capability in capabilities]

    assert len(gateways) == 8
    assert not hasattr(tool.reflector, "_prompt_gateway")
    assert all(isinstance(gateway, PromptGateway) for gateway in gateways)
    assert all(gateway is gateways[0] for gateway in gateways)
    other = build_tool()
    assert other.planner._prompt_gateway is not gateways[0]


def test_a_registry_path_is_relative_to_the_repository_not_the_launch_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_unit(tmp_path)
    registry = make_registry(tmp_path, example="v1")
    relative = registry.relative_to(ROOT)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    tool = build_tool(str(relative))
    rendered = tool.planner._prompt_gateway.render("example", ExampleParams(value="Red"))

    assert rendered.text == "Hello Red.\n"


def test_the_shared_assembly_factory_passes_the_registry_to_all_three_layers() -> None:
    tree = ast.parse((ROOT / "pokemon_agent/build.py").read_bytes())
    factory = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "brain"
    )
    build_call = next(
        node
        for node in ast.walk(factory)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "build"
    )

    registry = next(
        keyword.value for keyword in build_call.keywords if keyword.arg == "prompt_registry"
    )
    callers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "brain"
    ]

    assert ast.unparse(registry) == "app.prompt.registry"
    assert len(callers) == 3
