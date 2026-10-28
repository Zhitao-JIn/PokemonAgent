"""当前提示词的结构化观测字段优先级。"""

from pokemon_agent.prompt import (
    PromptGateway,
    VerifyParams,
)


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
