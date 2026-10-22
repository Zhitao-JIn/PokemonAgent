"""The public gateway's content hash is independent of checkout line endings."""

from pathlib import Path

from pokemon_agent.prompt import PromptGateway

from .unit_fixtures import ExampleParams, make_registry, make_unit


def test_lf_and_crlf_versions_have_the_same_hash(tmp_path: Path) -> None:
    make_unit(tmp_path / "lf")
    make_unit(tmp_path / "crlf", newline=b"\r\n")
    lf = PromptGateway(make_registry(tmp_path / "lf", example="v1"))
    crlf = PromptGateway(make_registry(tmp_path / "crlf", example="v1"))

    first = lf.render("example", ExampleParams(value="Red"))
    second = crlf.render("example", ExampleParams(value="Red"))

    assert first.hash == second.hash
    assert first.text == second.text == "Hello Red.\n"


def test_changing_one_prompt_character_changes_the_hash(tmp_path: Path) -> None:
    make_unit(tmp_path / "period", text="Hello {value}.\n")
    make_unit(tmp_path / "exclamation", text="Hello {value}!\n")
    first = PromptGateway(make_registry(tmp_path / "period", example="v1"))
    second = PromptGateway(make_registry(tmp_path / "exclamation", example="v1"))

    period = first.render("example", ExampleParams(value="Red"))
    exclamation = second.render("example", ExampleParams(value="Red"))

    assert period.hash != exclamation.hash


def test_changing_assembler_logic_also_changes_the_hash(tmp_path: Path) -> None:
    make_unit(tmp_path / "first", body="return params.value")
    make_unit(tmp_path / "second", body="return params.value.upper()")
    first = PromptGateway(make_registry(tmp_path / "first", example="v1"))
    second = PromptGateway(make_registry(tmp_path / "second", example="v1"))

    original = first.render("example", ExampleParams(value="Red"))
    changed = second.render("example", ExampleParams(value="Red"))

    assert original.hash != changed.hash
    assert original.text == "Red" and changed.text == "RED"
