"""活动版本网关与冻结 golden 文件逐字节对拍。"""

from pathlib import Path

import pytest

from pokemon_agent.prompt import (
    DecideActionParams,
    DecomposeParams,
    JudgeParams,
    PromptGateway,
    RunPlanParams,
    SummarizeParams,
    SummarizeRunParams,
    SummarizeTaskParams,
    VerifyParams,
)

from .golden_cases import GoldenCase, frozen_v1_registry, params_for
from .legacy_adapter import UnrestorableRequest

GOLDEN = Path(__file__).parent / "golden"
CONTRACTS = {
    "decide_action": DecideActionParams,
    "judge_success": JudgeParams,
    "decompose": DecomposeParams,
    "run_plan": RunPlanParams,
    "verify": VerifyParams,
    "summarize": SummarizeParams,
    "summarize_task": SummarizeTaskParams,
    "summarize_run": SummarizeRunParams,
}
REQUESTS = [path for path in sorted(GOLDEN.glob("*/*.req.json")) if path.parent.name in CONTRACTS]


@pytest.fixture(scope="module")
def gateway(tmp_path_factory: pytest.TempPathFactory) -> PromptGateway:
    """同一活动注册表服务独立输入，避免每条 golden 重复启动；黄金语料按捕获时的 v1 渲染。"""
    return PromptGateway(frozen_v1_registry(tmp_path_factory.mktemp("frozen")))


@pytest.mark.parametrize("path", REQUESTS, ids=lambda path: str(path.relative_to(GOLDEN)))
def test_gateway_prompt_preserves_the_frozen_bytes(path: Path, gateway: PromptGateway) -> None:
    case = GoldenCase.model_validate_json(path.read_bytes())
    try:
        params = params_for(case)
    except UnrestorableRequest as error:
        pytest.skip(str(error))
    actual = gateway.render(case.task, params)
    history = gateway.render_history(case.task, params) if case.task != "decide_action" else []

    expected = path.with_name(path.name.removesuffix(".req.json") + ".prompt.txt").read_bytes()
    assert actual.text.encode("utf-8") == expected
    assert actual.task == case.task
    assert actual.version == "v1"
    if case.task != "decide_action":
        assert all(isinstance(block, str) for block in history)
    if case.task == "decompose":
        assert "\n".join(history) in actual.text
    elif case.task == "run_plan":
        goals = gateway.render_history(case.task, params, part="goals")
        assert len(goals) == len(params.plan)
        assert all(line in actual.text for line in goals)


def test_snapshot_rendering_uses_structured_fields_ahead_of_old_text() -> None:
    facts = {
        "scene": "field",
        "overlay": "choice",
        "where": "stale",
        "neighbors": "stale",
        "options": ["YES", "NO"],
        "option_layout": "stale",
        "option_details": "stale",
        "neighbor_cells": {"up": "#", "down": ".", "left": "G", "right": "N"},
        "option_grid": [["YES"], ["NO"]],
        "cursor_cell": [1, 0],
        "option_annotations": ["x2", ""],
    }
    observation = {
        "step": 1,
        "status": "unused",
        "place": {"map_id": 1, "x": 2, "y": 3},
        "facts": facts,
    }
    entry = {
        "before": observation,
        "after": observation,
        "action": "a",
        "step": 1,
        "episode_id": "e",
    }
    params = VerifyParams.model_validate({"goal": "g", "entries": [entry]})
    gateway = PromptGateway(None)

    text = gateway.render("verify", params).text

    assert "stale" not in text
    assert "全局坐标 地图1 x=2 y=3" in text
    assert "北 # 南 . 西 G 东 N" in text
    assert "竖排 2 项，光标在第 2 项；上/下 移动光标" in text
    assert "YES x2" in text


def test_explicitly_empty_structured_fields_suppress_stale_legacy_projections() -> None:
    facts = {
        "scene": "field",
        "neighbors": "STALE_PROJECTION",
        "option_layout": "STALE_PROJECTION",
        "option_details": "STALE_PROJECTION",
        "my_name": "STALE_PROJECTION",
        "neighbor_cells": {},
        "option_grid": [],
        "option_annotations": [],
        "battle_status": None,
    }
    observation = {"step": 1, "status": "unused", "facts": facts}
    entry = {
        "before": observation,
        "after": observation,
        "action": "a",
        "step": 1,
        "episode_id": "e",
    }
    params = VerifyParams.model_validate({"goal": "g", "entries": [entry]})

    text = PromptGateway(None).render("verify", params).text

    assert "STALE_PROJECTION" not in text
