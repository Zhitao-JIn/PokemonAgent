"""已迁移任务通过活动版本网关与同源素材渲染逐字节对拍。"""

from pathlib import Path

import pytest

from pokemon_agent.direct.prompts import summarize, summarize_run, summarize_task
from pokemon_agent.prompt import (
    PromptGateway,
    SummarizeParams,
    SummarizeRunParams,
    SummarizeTaskParams,
    VerifyParams,
)
from scripts.capture_prompt_golden import GoldenCase, parse_request

from .legacy_adapter import UnrestorableRequest, adapt_request

GOLDEN = Path(__file__).parent / "golden"
CONTRACTS = {
    "verify": VerifyParams,
    "summarize": SummarizeParams,
    "summarize_task": SummarizeTaskParams,
    "summarize_run": SummarizeRunParams,
}
REQUESTS = [path for path in sorted(GOLDEN.glob("*/*.req.json")) if path.parent.name in CONTRACTS]


@pytest.mark.parametrize("path", REQUESTS, ids=lambda path: str(path.relative_to(GOLDEN)))
def test_migrated_prompt_and_history_preserve_the_old_contract(path: Path) -> None:
    case = GoldenCase.model_validate_json(path.read_bytes())
    try:
        adapted = adapt_request(case.request)
    except UnrestorableRequest as error:
        pytest.skip(str(error))
    req = parse_request(case.model_copy(update={"request": adapted.request}))
    data = req.model_dump(mode="json")
    if case.task in ("summarize", "summarize_task"):
        data["success"] = req.success
    params = CONTRACTS[case.task].model_validate(data)
    gateway = PromptGateway(None)
    if case.task == "verify":
        expected_history = [entry.render() for entry in req.entries]
    elif case.task == "summarize":
        expected_history = summarize.labeled_blocks(
            [entry.render() for entry in req.entries], req.verdicts
        )
    elif case.task == "summarize_task":
        expected_history = summarize_task.history_blocks(req)
    else:
        expected_history = summarize_run.history_blocks(req)

    actual = gateway.render(case.task, params)
    history = gateway.render_history(case.task, params)

    expected = path.with_name(path.name.removesuffix(".req.json") + ".prompt.txt").read_bytes()
    assert actual.text.encode("utf-8") == expected
    assert history == expected_history
    assert actual.task == case.task
    assert actual.version == "v1"


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
