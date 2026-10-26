"""三个 plan 的场合裁剪与动态输入不污染固定前缀。"""

import pytest

from pokemon_agent.prompt import PromptGateway

from .layout_examples import examples

TASKS = ("run_plan", "decompose", "decide_action")


@pytest.mark.parametrize("task", TASKS)
def test_live_feedback_and_budget_changes_do_not_change_the_static_prefix(task: str) -> None:
    params = examples()[task]
    gateway = PromptGateway(None)
    original = gateway.render(task, params).text
    obs = params.observation
    assert obs is not None
    changed = params.model_copy(
        update={
            "observation": obs.model_copy(
                update={
                    "step": 3,
                    "facts": obs.facts.model_copy(
                        update={"overlay": "dialog", "dialog_text": "新对话"}
                    ),
                }
            ),
            "human_note": "新插话",
            "budget_context": [],
        }
    )

    actual = gateway.render(task, changed).text

    assert original.split("## 本次输入", 1)[0] == actual.split("## 本次输入", 1)[0]
    assert "新对话" in actual and actual != original


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("overlay", ["none", "dialog", "choice"])
def test_every_plan_uses_the_same_scene_projection_without_object_lines(
    task: str,
    overlay: str,
) -> None:
    params = examples()[task]
    obs = params.observation
    assert obs is not None
    obs = obs.model_copy(
        update={
            "facts": obs.facts.model_copy(
                update={
                    "overlay": overlay,
                    "screen": "  MENU\n  YES",
                    "dialog_text": "现场对话",
                }
            )
        }
    )
    params = params.model_copy(update={"observation": obs})
    reference = examples()["decide_action"].model_copy(update={"observation": obs})
    expected = PromptGateway(None).render("decide_action", reference).text
    expected = expected.split("\n## 当前现场\n", 1)[1].split("可用动作：", 1)[0].strip()

    text = PromptGateway(None).render(task, params).text

    assert expected in text
    assert "- known_objects:" not in text.split("\n## 当前现场\n", 1)[1]
    if task == "decide_action" and overlay != "none":
        assert "\n## 地图交互事实\n" not in text
        assert "完整招牌原文。" not in text
    else:
        assert "完整招牌原文。" in text.split("\n## 地图交互事实\n", 1)[1]


@pytest.mark.parametrize("scene", ["walk", "shop", "dialog", "start_menu"])
@pytest.mark.parametrize("overlay", ["none", "dialog", "choice"])
def test_choose_keeps_the_original_object_visibility(scene: str, overlay: str) -> None:
    params = examples()["decide_action"]
    obs = params.observation.model_copy(
        update={
            "scene": scene,
            "facts": params.observation.facts.model_copy(update={"overlay": overlay}),
        }
    )

    text = (
        PromptGateway(None)
        .render("decide_action", params.model_copy(update={"observation": obs}))
        .text
    )

    visible = scene in {"walk", "shop"} and overlay == "none"
    assert ("\n## 地图交互事实\n" in text) == visible
    assert ("完整招牌原文。" in text) == visible
