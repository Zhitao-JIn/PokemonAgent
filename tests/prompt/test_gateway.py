"""Load a temporary registry and render through the single public gateway."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from pokemon_agent.prompt import PromptGateway, RenderedPrompt

from .unit_fixtures import ExampleParams, file_hash, make_registry, make_unit


def test_a_render_contains_text_task_version_and_the_source_hash(tmp_path: Path) -> None:
    directory = make_unit(tmp_path, version="v2")
    registry = make_registry(tmp_path, example="v2")
    gateway = PromptGateway(registry)

    rendered = gateway.render("example", ExampleParams(value="Red"))

    assert rendered == RenderedPrompt(
        text="Hello Red.\n", task="example", version="v2", hash=file_hash(directory)
    )


def test_the_bundled_registry_has_no_real_tasks() -> None:
    gateway = PromptGateway(None)

    with pytest.raises(AssertionError, match="not registered"):
        gateway.render("verify", ExampleParams(value="Red"))


def test_an_unregistered_task_is_a_caller_contract_error(tmp_path: Path) -> None:
    gateway = PromptGateway(make_registry(tmp_path))

    with pytest.raises(AssertionError, match="not registered"):
        gateway.render("unknown", ExampleParams(value="Red"))


def test_a_fragment_cannot_be_rendered_as_a_task(tmp_path: Path) -> None:
    make_unit(tmp_path, name="shared", kind="fragment")
    gateway = PromptGateway(make_registry(tmp_path, shared="v1"))

    with pytest.raises(AssertionError, match="kind=task"):
        gateway.render("shared", ExampleParams(value="Red"))


def test_params_must_be_exactly_the_declared_contract(tmp_path: Path) -> None:
    class OtherParams(BaseModel):
        value: str

    make_unit(tmp_path)
    gateway = PromptGateway(make_registry(tmp_path, example="v1"))

    with pytest.raises(AssertionError, match="Wrong params type"):
        gateway.render("example", OtherParams(value="Red"))


def test_a_contract_subclass_is_not_the_declared_contract(tmp_path: Path) -> None:
    class MoreParams(ExampleParams):
        extra: str = ""

    make_unit(tmp_path)
    gateway = PromptGateway(make_registry(tmp_path, example="v1"))

    with pytest.raises(AssertionError, match="Wrong params type"):
        gateway.render("example", MoreParams(value="Red"))


def test_an_empty_render_violates_the_assembler_postcondition(tmp_path: Path) -> None:
    make_unit(tmp_path, body='return ""')
    gateway = PromptGateway(make_registry(tmp_path, example="v1"))

    with pytest.raises(AssertionError, match="Empty or non-string"):
        gateway.render("example", ExampleParams(value="Red"))


def test_a_standalone_copy_uses_packaged_units_with_a_registry_stored_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path(__file__).resolve().parents[2] / "pokemon_agent/prompt"
    destination = tmp_path / "standalone_prompt"
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__"))
    make_unit(destination)
    registry = make_registry(tmp_path / "configuration", example="v1")
    specification = importlib.util.spec_from_file_location(
        "standalone_prompt",
        destination / "__init__.py",
        submodule_search_locations=[str(destination)],
    )
    module = importlib.util.module_from_spec(specification)
    monkeypatch.setitem(sys.modules, "standalone_prompt", module)
    specification.loader.exec_module(module)

    rendered = module.PromptGateway(registry).render("example", ExampleParams(value="Red"))

    assert rendered.text == "Hello Red.\n"
    assert module.__all__ == ["PromptGateway", "RenderedPrompt", "PromptRegistryError"]
