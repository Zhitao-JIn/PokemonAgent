"""记忆片段 v3 的用法示范：脚本对话按行渲染在结果行之后，空对话与 v2 逐字相同。

**为什么走临时包装任务**：`memory_records` 是 `kind=fragment`，网关只渲染 `kind=task`，
版本的 `assemble.py` 也不许从外部 import（`docs/prompt_module/spec.md` D4）。所以这里
照 `test_distillation_fragments.py` 的做法，建一个把 `MemoryParams` 转交给 `compose`
的最小任务，再经公开网关渲染——测的是真实加载路径，不是把 md 读进来数行。

**只走公开出口**：`scripts/check_prompt_boundary.py` 的规则 B 要求包外只能
`from pokemon_agent.prompt import <__all__ 里的名字>`，所以本文件不 import 任何
prompt 内部模块；记录以 harness 实际传的 JSON 形状喂进去（`ActMemory.model_dump()`
就是 dict），`MemoryParams` 的构造落在临时任务的 `assemble.py` 里（那份文件在
`tmp_path` 下，不是仓库代码）。

**两种形状都要测**：`plain` / `verify_entries` 走 `act_render`（有 `结果` 行），
`sequence` 走 `act_sequence`（没有 `结果` 行，`decide_action` 的历史素材就是它）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from pokemon_agent.prompt import PromptGateway

from .unit_fixtures import ExampleParams, make_unit

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / "pokemon_agent/prompt/tasks/fragments/memory_records"
PACKAGE_REGISTRY = ROOT / "pokemon_agent/prompt/registry.json"

Render = Callable[[dict[str, object]], str]


def _registry(root: Path, active: str) -> Path:
    """包注册表的副本：只把 memory_records 的活动版本指到 `active`，再加一个包装任务。"""
    data = json.loads(PACKAGE_REGISTRY.read_bytes())
    data["tasks"]["memory_records"] = {"active": active}
    make_unit(
        root,
        "example_memory_records",
        body=(
            "from pokemon_agent.prompt.tasks.fragments.memory_records.params import MemoryParams\n"
            'return compose("memory_records", MemoryParams.model_validate_json(params.value))'
        ),
    )
    data["tasks"]["example_memory_records"] = {"active": "v1"}
    path = root / "registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _renderer(registry: Path) -> Render:
    gateway = PromptGateway(registry)
    return lambda params: (
        gateway.render(
            "example_memory_records", ExampleParams(value=json.dumps(params, ensure_ascii=False))
        ).text
    )


@pytest.fixture()
def render_v3(tmp_path: Path) -> Render:
    return _renderer(_registry(tmp_path / "three", "v3"))


@pytest.fixture()
def render_v2(tmp_path: Path) -> Render:
    return _renderer(_registry(tmp_path / "two", "v2"))


def _record(
    *,
    step: int = 0,
    action: str = "script:advance_dialog(max_presses=10)",
    result: str = "ok",
    dialog: list[str] | None = None,
    episode_id: str = "ep",
) -> dict[str, object]:
    """一条最小 ActMemory JSON 形状：观测只给 status，够渲染又不会把断言埋进地形图。"""
    return {
        "before": {"step": step, "status": "野外"},
        "action": action,
        "after": {"step": step + 1, "status": "野外"},
        "result": result,
        "dialog": list(dialog or []),
        "step": step,
        "episode_id": episode_id,
    }


def _params(mode: str, entries: list[dict[str, object]]) -> dict[str, object]:
    return {"mode": mode, "entries": entries}


def _lines(text: str) -> list[str]:
    return text.splitlines()


def test_dialog_lines_render_after_the_result_line_in_input_order(render_v3: Render) -> None:
    """每一行落在 `结果` 之后、`之后变成` 之前，顺序与输入一致。"""
    text = render_v3(_params("plain", [_record(dialog=["收件人 PROF. OAK", "包裹在 PALLET TOWN"])]))
    lines = _lines(text)

    result_at = next(i for i, line in enumerate(lines) if "结果" in line)
    first_dialog = next(i for i, line in enumerate(lines) if "收件人 PROF. OAK" in line)
    second_dialog = next(i for i, line in enumerate(lines) if "包裹在 PALLET TOWN" in line)
    after_at = next(i for i, line in enumerate(lines) if "之后变成" in line)

    assert lines[result_at].strip().startswith("结果")
    assert lines[first_dialog].strip().startswith("对话")
    assert result_at < first_dialog < second_dialog < after_at


def test_dialog_renders_in_sequence_mode_which_has_no_result_line(render_v3: Render) -> None:
    """`sequence`（decide_action 的历史素材）没有结果行，对话落在"做了"之后。"""
    text = render_v3(
        _params(
            "sequence",
            [_record(step=0, dialog=["第一行"]), _record(step=1, action="up", result="")],
        )
    )
    lines = _lines(text)

    action_at = next(i for i, line in enumerate(lines) if line.strip().startswith("做了"))
    dialog_at = next(i for i, line in enumerate(lines) if "第一行" in line)
    after_at = next(i for i, line in enumerate(lines) if "之后变成" in line)

    assert action_at < dialog_at < after_at


def test_two_hundred_dialog_lines_are_not_truncated(render_v3: Render) -> None:
    """200 行样例逐行渲染，一行不少、一句不截。"""
    dialog = [f"第 {index:03d} 行：这是一句要完整保留下来的台词。" for index in range(200)]

    text = render_v3(_params("plain", [_record(dialog=dialog)]))

    rendered = [line.strip() for line in _lines(text) if line.strip().startswith("对话")]
    assert len(rendered) == 200
    assert [line.removeprefix("对话").strip() for line in rendered] == dialog


def test_empty_dialog_renders_byte_identical_to_v2(render_v3: Render, render_v2: Render) -> None:
    """对话为空（按键动作、旧记忆）时，v3 与 v2 的输出逐字相同。"""
    params = _params(
        "plain",
        [
            _record(step=0, action="up", result="", dialog=[]),
            _record(step=1, dialog=[]),
        ],
    )

    assert render_v3(params) == render_v2(params)


def test_old_versions_still_load_against_their_recorded_hashes(tmp_path: Path) -> None:
    """旧版本源文件没被动过：网关构造时重算 hash，与各自 meta.json 里的一致才加载。"""
    for version in ("v1", "v2"):
        gateway = PromptGateway(_registry(tmp_path / version, version))

        rendered = gateway.render(
            "example_memory_records", ExampleParams(value=json.dumps(_params("plain", [_record()])))
        )
        assert rendered.text


def test_package_registry_activates_v4_and_preserves_v3(tmp_path: Path) -> None:
    """活动版本为 v4，旧版 v3 仍可加载并渲染。"""
    data = json.loads(PACKAGE_REGISTRY.read_bytes())
    assert data["tasks"]["memory_records"]["active"] == "v5"

    meta = json.loads((FRAGMENT / "v3/meta.json").read_bytes())
    assert meta["version"] == "v3" and meta["params"] == "MemoryParams"

    PromptGateway(None)  # 任一条不一致都会在构造时抛 PromptRegistryError

    render = _renderer(_registry(tmp_path, "v3"))
    assert "第一行" in render(_params("plain", [_record(dialog=["第一行"])]))
