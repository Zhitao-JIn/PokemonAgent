"""历史裁定标签按 judge 请求中的完整历史核对。"""

from evals.dataset.brain_judge.build.adjudicate_candidates import adjudicate_candidate


def _row(criteria: str, history: list[dict]) -> dict:
    return {
        "candidate_id": "sample@1",
        "event_uuid": "event-1",
        "goal_family": "interaction",
        "criteria": criteria,
        "suggested_achieved": None,
        "request": {"history": history},
    }


def _memory(
    where: str,
    facing: str = "north",
    dialog: str = "",
    options: list[str] | None = None,
    cursor: str | None = None,
):
    return {
        "scene": "walk",
        "facts": {
            "where": where,
            "facing": facing,
            "dialog_text": dialog,
            "options": options or [],
            "cursor": cursor,
        },
    }


def test_adjudication_keeps_a_location_goal_once_history_reached_it() -> None:
    row = _row(
        "where 显示 x=5 y=5 且 facing 为 south",
        [
            {
                "before": _memory("全局坐标 地图42 x=5 y=4"),
                "after": _memory("全局坐标 地图42 x=5 y=5", "south"),
            },
            {
                "before": _memory("全局坐标 地图42 x=5 y=5", "south"),
                "after": _memory("全局坐标 地图42 x=5 y=6", "south"),
            },
        ],
    )

    result = adjudicate_candidate(row)

    assert result.achieved is True
    assert "history[0].after" in result.evidence_locator


def test_adjudication_requires_both_shop_dialogue_and_later_menu() -> None:
    row = _row(
        "对话框里出现过店员的话，且之后出现 BUY / SELL / QUIT 选项",
        [
            {
                "before": _memory("地图42 x=4 y=6"),
                "after": _memory("地图42 x=4 y=6", dialog="This shop sells many ANTIDOTEs."),
            },
        ],
    )

    result = adjudicate_candidate(row)

    assert result.achieved is False
    assert result.negative_mode == "near_miss"


def test_adjudication_uses_throw_and_battle_events_from_earlier_history() -> None:
    throw_row = _row(
        "对话框出现投球相关文字或投出球提示",
        [
            {
                "before": _memory("地图12 x=13 y=7", options=["POTION", "POKé BALL"]),
                "after": _memory("地图12 x=13 y=7", options=["POTION", "POKé BALL"]),
            },
            {
                "before": _memory("地图12 x=13 y=7"),
                "after": _memory("地图12 x=13 y=7", dialog="All right! PIDGEY was"),
            },
        ],
    )
    battle_row = _row(
        "场景不再是 battle，或出现战斗结束文字",
        [
            {
                "before": _memory("地图12 x=12 y=24"),
                "after": {"scene": "battle", "facts": {"dialog_text": "Enemy RATTATA fainted!"}},
            },
            {
                "before": {"scene": "battle", "facts": {}},
                "after": {
                    "scene": "battle",
                    "facts": {"dialog_text": "BULBASAUR gained 24 EXP. Points!"},
                },
            },
        ],
    )

    assert adjudicate_candidate(throw_row).achieved is True
    assert adjudicate_candidate(battle_row).achieved is True


def test_selected_ball_is_not_a_throw_and_battle_menu_is_still_battle() -> None:
    ball_row = _row(
        "屏幕出现精灵球被选用的提示文字，或对话框里出现投球相关文字",
        [
            {
                "before": _memory(
                    "地图12 x=13 y=7", options=["POTION", "POKé BALL"], cursor="POKé BALL"
                ),
                "after": {
                    **_memory(
                        "地图12 x=13 y=7", options=["POTION", "POKé BALL"], cursor="POKé BALL"
                    ),
                    "scene": "battle_menu",
                },
            }
        ],
    )
    battle_row = _row(
        "场景不再是 battle，或出现战斗结束文字",
        [
            {
                "before": {"scene": "battle_menu", "facts": {}},
                "after": {"scene": "battle_menu", "facts": {}},
            }
        ],
    )

    ball_result = adjudicate_candidate(ball_row)
    battle_result = adjudicate_candidate(battle_row)

    assert ball_result.achieved is False
    assert ball_result.negative_mode == "near_miss"
    assert battle_result.achieved is False
