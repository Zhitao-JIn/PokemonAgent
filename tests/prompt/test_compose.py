"""Task assemblers compose registered fragments through the injected callable."""

from pathlib import Path

import pytest

from pokemon_agent.prompt import PromptGateway, PromptRegistryError

from .unit_fixtures import ExampleParams, make_registry, make_unit


def test_a_task_can_compose_a_registered_fragment(tmp_path: Path) -> None:
    make_unit(tmp_path, "shared", kind="fragment", text="[{value}]\n")
    make_unit(tmp_path, body='return compose("shared", params) + params.value')
    gateway = PromptGateway(make_registry(tmp_path, example="v1", shared="v1"))

    rendered = gateway.render("example", ExampleParams(value="Red"))

    assert rendered.text == "[Red]\nRed"
    assert rendered.task == "example" and rendered.version == "v1"


def test_compose_refuses_a_registered_task(tmp_path: Path) -> None:
    make_unit(tmp_path, "other_task")
    make_unit(tmp_path, body='return compose("other_task", params)')
    registry = make_registry(tmp_path, example="v1", other_task="v1")

    with pytest.raises(PromptRegistryError, match="compose requires kind=fragment"):
        PromptGateway(registry)
