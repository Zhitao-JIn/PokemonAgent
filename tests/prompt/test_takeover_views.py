"""独立复制模块通过注册任务组合真实的八类业务视图片段。"""

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from pokemon_agent.world.interface.domain.takeover_view import TakeoverView

from .unit_fixtures import ExampleParams, make_registry, make_unit

ROOT = Path(__file__).resolve().parents[2]
CASES = sorted(
    (Path(__file__).parent / "golden/decide_action").glob("synthetic-takeover-*.req.json")
)
CASES = [path for path in CASES if path.name != "synthetic-takeover-missing.req.json"]


@pytest.mark.parametrize("path", CASES, ids=lambda path: path.stem)
def test_each_takeover_view_matches_the_legacy_text_in_an_independent_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
) -> None:
    raw = json.loads(path.read_bytes())["request"]["obs"]["takeover"]
    old_view = TypeAdapter(TakeoverView).validate_python(raw)
    directory = tmp_path / "isolated"
    shutil.copytree(
        ROOT / "pokemon_agent/prompt", directory, ignore=shutil.ignore_patterns("__pycache__")
    )
    make_unit(
        directory,
        body=(
            "from ..fragments.takeover.params import TakeoverParams\n"
            "return compose('takeover', TakeoverParams.model_validate_json(params.value))"
        ),
    )
    registry = make_registry(tmp_path / "configuration", example="v1", takeover="v1")
    name = "isolated_takeover_" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(
        name, directory / "__init__.py", submodule_search_locations=[str(directory)]
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)

    result = module.PromptGateway(registry).render(
        "example", ExampleParams(value=json.dumps({"view": raw}))
    )

    assert result.text == old_view.render()
    assert result.task == "example"


def test_the_takeover_examples_cover_all_eight_discriminators() -> None:
    assert len(CASES) == 8
