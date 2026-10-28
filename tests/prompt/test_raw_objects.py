"""原始事件文字只在版本内还原：适配器只恢复文本里出现过的信息。"""

import pytest

from pokemon_agent.prompt import DecomposeParams, PromptGateway
from pokemon_agent.world import TERRAIN_MEANING, TaskObservation, TaskScene

from .legacy_adapter import restore_object_events


@pytest.mark.parametrize("outcome", ["dialog", "warp", "still"])
def test_text_adapter_restores_only_information_present_in_the_text(outcome: str) -> None:
    result = {
        "dialog": '对话"你好"朋友"\n下一行"',
        "warp": "进入新地图9",
        "still": "无效果",
    }[outcome]
    text = (
        "ep step1 站在 x=-2 y=3 按 a → 地图1 x=-2 y=4 的人：无效果\n"
        f"ep step2 站在 x=-2 y=3 按 a → 地图1 x=-2 y=4 的人：{result}"
    )
    raw = restore_object_events(text)
    obs = TaskObservation(facts={"overlay": "none"}, step=4, scene=TaskScene.WALK)
    params = DecomposeParams.model_validate(
        {
            "goal": {"goal": "g", "criteria": "c"},
            "observation": obs.model_dump(mode="json"),
            "max_tasks": 3,
            "terrain_meanings": TERRAIN_MEANING,
            "known_objects": raw,
        }
    )

    actual = PromptGateway(None).render("decompose", params)

    assert "run_id" not in raw[0] and "map_id" not in raw[0]["actor_place"]
    for line in text.splitlines():
        assert line.removeprefix("ep ") in actual.text
    assert "ep step" not in actual.text
    assert actual.text.index("step1 站在") < actual.text.index("step2 站在")
