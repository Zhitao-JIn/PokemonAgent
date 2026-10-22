"""活动版本网关与冻结 golden 文件逐字节对拍。"""

from pathlib import Path

import pytest

from pokemon_agent.direct.brain_tool import decide_prompt_params
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
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.schemas.memory.datastore.act_memory import render_sequence
from pokemon_agent.world import TERRAIN_MEANING

from .golden_cases import GoldenCase, parse_request
from .legacy_adapter import UnrestorableRequest, adapt_request

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
def gateway() -> PromptGateway:
    """同一活动注册表服务独立输入，避免每条 golden 重复启动。"""
    return PromptGateway(None)


@pytest.mark.parametrize("path", REQUESTS, ids=lambda path: str(path.relative_to(GOLDEN)))
def test_gateway_prompt_preserves_the_frozen_bytes(path: Path, gateway: PromptGateway) -> None:
    case = GoldenCase.model_validate_json(path.read_bytes())
    try:
        adapted = adapt_request(case.request)
    except UnrestorableRequest as error:
        pytest.skip(str(error))
    req = parse_request(case.model_copy(update={"request": adapted.request}))
    data = req.model_dump(mode="json")
    if case.task in ("summarize", "summarize_task"):
        data["success"] = req.success
    if case.task == "decompose":
        data["terrain_meanings"] = TERRAIN_MEANING
    params = (
        decide_prompt_params(req, max_segments=case.max_segments)
        if case.task == "decide_action"
        else CONTRACTS[case.task].model_validate(data)
    )
    if adapted.prompt_fields:
        params = CONTRACTS[case.task].model_validate(
            {**params.model_dump(mode="json"), **adapted.prompt_fields}
        )
    actual = gateway.render(case.task, params)
    history = gateway.render_history(case.task, params) if case.task != "decide_action" else []

    expected = path.with_name(path.name.removesuffix(".req.json") + ".prompt.txt").read_bytes()
    assert actual.text.encode("utf-8") == expected
    assert actual.task == case.task
    assert actual.version == "v1"
    if case.task == "verify":
        assert history == [entry.render() for entry in req.entries]
    elif case.task in {"summarize", "summarize_task"}:
        entries = req.entries
        records = (
            render_sequence(entries)
            if entries and isinstance(entries[0], ActMemory)
            else [entry.render() for entry in entries]
        )
        verdicts = {verdict.index: verdict for verdict in req.verdicts}
        expected_blocks = []
        for index, record in enumerate(records):
            verdict = verdicts.get(index)
            tag = "【未校验】"
            if verdict is not None:
                tag = ("【正样本】" if verdict.positive else "【负样本】") + verdict.why
            expected_blocks.append(f"## 第 {index} 条 {tag}\n{record}")
        assert history == expected_blocks
    elif case.task == "summarize_run":
        assert history == [entry.render() for entry in req.episode_memories]
    elif case.task == "judge_success":
        assert history[: len(req.history)] == [entry.render() for entry in req.history]
    elif case.task == "decompose":
        assert "\n".join(history) in actual.text
    elif case.task == "run_plan":
        assert history[: len(req.details)] == [entry.render() for entry in req.details]
        goals = gateway.render_history(case.task, params, part="goals")
        assert len(goals) == len(req.plan)
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
