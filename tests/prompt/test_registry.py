"""Invalid registries fail at construction before any task can render."""

from pathlib import Path

import pytest

from pokemon_agent.prompt import PromptGateway, PromptRegistryError

from .unit_fixtures import make_registry, make_unit


def test_a_changed_prompt_without_a_new_hash_is_rejected_at_startup(tmp_path: Path) -> None:
    directory = make_unit(tmp_path)
    registry = make_registry(tmp_path, example="v1")
    original = (directory / "prompt.md").read_bytes()
    (directory / "prompt.md").write_bytes(original.replace(b".", b"!", 1))

    with pytest.raises(PromptRegistryError, match="hash mismatch"):
        PromptGateway(registry)


def test_a_missing_version_directory_is_rejected_at_startup(tmp_path: Path) -> None:
    make_unit(tmp_path)
    registry = make_registry(tmp_path, example="v2")

    with pytest.raises(PromptRegistryError, match="Version directory missing"):
        PromptGateway(registry)


def test_a_missing_contract_class_is_rejected_at_startup(tmp_path: Path) -> None:
    directory = make_unit(tmp_path)
    (directory.parent / "params.py").write_bytes(b"from pydantic import BaseModel\n")
    registry = make_registry(tmp_path, example="v1")

    with pytest.raises(PromptRegistryError, match="Contract class missing"):
        PromptGateway(registry)


def test_an_unregistered_fragment_is_rejected_at_startup(tmp_path: Path) -> None:
    make_unit(tmp_path, body='return compose("missing", params)')
    registry = make_registry(tmp_path, example="v1")

    with pytest.raises(PromptRegistryError, match="fragment not registered: missing"):
        PromptGateway(registry)


def test_a_nonliteral_fragment_cannot_escape_startup_validation(tmp_path: Path) -> None:
    make_unit(tmp_path, body="return compose(params.value, params)")
    registry = make_registry(tmp_path, example="v1")

    with pytest.raises(PromptRegistryError, match="compose name must be literal"):
        PromptGateway(registry)


def test_a_fragment_cycle_is_rejected_at_startup(tmp_path: Path) -> None:
    make_unit(tmp_path, "first", kind="fragment", body='return compose("second", params)')
    make_unit(tmp_path, "second", kind="fragment", body='return compose("first", params)')
    registry = make_registry(tmp_path, first="v1", second="v1")

    with pytest.raises(PromptRegistryError, match="Composition cycle"):
        PromptGateway(registry)
