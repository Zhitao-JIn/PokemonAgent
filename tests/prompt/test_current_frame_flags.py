"""当前帧限制标志的显式值与旧输入推导保持一致。"""

from pokemon_agent.prompt import DecideActionParams, PromptGateway


def render_frame(*, explicit: bool) -> str:
    observation: dict[str, object] = {
        "step": 0,
        "scene": "dialog",
        "facts": {"overlay": "dialog"},
        "menu_decode_complete": False,
    }
    if explicit:
        observation["observation_flags"] = ["no_text", "incomplete_menu"]
    params = DecideActionParams.model_validate(
        {
            "goals": [{"goal": "g", "criteria": "c"}],
            "observation": observation,
            "space": {"names": ["a"]},
            "max_segments": 1,
            "terrain_meanings": {"#": "墙"},
        }
    )
    return PromptGateway(None).render("decide_action", params).text


def test_current_frame_keeps_limit_notes_with_and_without_explicit_flags() -> None:
    explicit = render_frame(explicit=True)
    derived = render_frame(explicit=False)

    for phrase in (
        "未解码出屏幕文字，不能据此判断界面已结束",
        "选单切分不完整，不能用空选项判断没有选单",
    ):
        assert phrase in explicit and phrase in derived
