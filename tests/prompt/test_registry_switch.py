"""Switching a task's active version is a registry edit, never a code change.

反例（`active` 指向不存在的版本 → 构造即抛 `PromptRegistryError`）已由
`test_registry.py::test_a_missing_version_directory_is_rejected_at_startup` 覆盖，此处不重复。
"""

import json
from pathlib import Path

from pokemon_agent.prompt import PromptGateway

from .unit_fixtures import ExampleParams, file_hash, make_registry, make_unit


def test_editing_only_the_active_version_switches_the_rendered_prompt(tmp_path: Path) -> None:
    first = make_unit(tmp_path, version="v1", text="First version for {value}.\n")
    second = make_unit(tmp_path, version="v2", text="Second version for {value}.\n")
    registry = make_registry(tmp_path, example="v1")
    params = ExampleParams(value="Red")
    sources = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*.py")}

    before = PromptGateway(registry).render("example", params)

    make_registry(tmp_path, example="v2")
    after = PromptGateway(registry).render("example", params)

    assert (before.version, before.text, before.hash) == (
        "v1",
        "First version for Red.\n",
        file_hash(first),
    )
    assert (after.version, after.text, after.hash) == (
        "v2",
        "Second version for Red.\n",
        file_hash(second),
    )
    assert (before.hash, before.text) != (after.hash, after.text)
    assert {
        path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*.py")
    } == sources
    assert json.loads(registry.read_bytes())["tasks"]["example"]["active"] == "v2"
