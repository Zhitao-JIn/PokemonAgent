"""感知层数据模型的测试 —— 二元组结构到底买到了什么。

这些测试的第一读者是"想知道为什么界面类型是二元组"的人，
所以每个测试都在验证一条设计主张，而不是覆盖率。
"""

from __future__ import annotations

import pytest

from pokemon_agent.schemas.screen import (
    OVERLAY_ACTIONS,
    SCENE_FIELDS,
    Overlay,
    Scene,
    ScreenState,
)


def test_action_mask_depends_only_on_overlay():
    """核心主张：同一个 overlay，在任何 scene 下动作集都一样。

    这正是二元组省下来的东西——扁平枚举要为每个「场合×叠加层」重复写一遍掩码。
    """
    masks = {
        ScreenState(scene=scene, overlay=Overlay.DIALOG).available_actions()
        for scene in Scene
    }

    assert len(masks) == 1, "对话框下的动作集不该随场合变化"
    assert masks.pop() == ("a",), "对话框只能推进，方向键无效"


def test_the_two_battle_menus_are_the_same_type_and_differ_only_in_options():
    """`FIGHT/ITEM/PKMN/RUN` 和 `TACKLE/GROWL` 都是 CHOICE，区别在数据不在类型。

    扁平枚举会逼你给每个菜单开一个新类型，而它们可按的键完全一样。
    """
    main_menu = ScreenState(
        scene=Scene.BATTLE, overlay=Overlay.CHOICE,
        options=["FIGHT", "ITEM", "PKMN", "RUN"], cursor=0,
    )
    move_menu = ScreenState(
        scene=Scene.BATTLE, overlay=Overlay.CHOICE, options=["TACKLE", "GROWL"], cursor=0,
    )

    assert main_menu.overlay is move_menu.overlay
    assert main_menu.available_actions() == move_menu.available_actions()
    assert main_menu.options != move_menu.options


def test_dialog_is_an_overlay_not_a_scene():
    """研究所里的对话框 = 室内 + 对话框，不是"对话框"这个独立类型。

    这就是扁平枚举答不上来的那个问题：它到底算"室内"还是算"对话框"。
    """
    indoors = ScreenState(
        scene=Scene.INDOOR, overlay=Overlay.DIALOG, dialog_text="AK! Gramps! Smell you later!"
    )
    in_battle = ScreenState(
        scene=Scene.BATTLE, overlay=Overlay.DIALOG, dialog_text="AC wants to fight!"
    )

    # 场合不同（字段不同），叠加层相同（动作相同）
    assert indoors.expected_fields() != in_battle.expected_fields()
    assert indoors.available_actions() == in_battle.available_actions()


def test_every_enum_value_has_a_table_entry():
    """两张表必须覆盖全部枚举值。

    漏一个不会报错，只会在运行时 KeyError——而那时已经在跑实验了。
    新增 scene / overlay 时这个测试会当场提醒你补表。
    """
    assert set(OVERLAY_ACTIONS) == set(Overlay)
    assert set(SCENE_FIELDS) == set(Scene)


def test_missing_fields_are_absent_not_placeholder():
    """读不出的字段直接不放，而不是填空串或 "unknown"。

    分不清"没读到"和"读到了空"，会污染状态抽象准确率的标定——
    那个数字是要写进简历的，不能建立在把缺失当成功的统计上。
    """
    partial = ScreenState(
        scene=Scene.BATTLE, overlay=Overlay.NONE, fields={"my_name": "CHARMANDER"}
    )

    assert "foe_hp" not in partial.fields
    missing = [f for f in partial.expected_fields() if f not in partial.fields]
    assert len(missing) == 5, "6 个期望字段里读到 1 个，缺 5 个"


@pytest.mark.parametrize("overlay", list(Overlay))
def test_action_masks_are_never_empty(overlay: Overlay):
    """空动作空间是 bug（见 ToolPort 契约）。走投无路也必须至少给一个键。"""
    assert OVERLAY_ACTIONS[overlay], f"{overlay} 的动作集不能为空"
