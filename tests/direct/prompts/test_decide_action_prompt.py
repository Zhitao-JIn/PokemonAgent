"""`decide_action.md` 的「## 目标」那一节长什么样。

**为什么单独钉这一节**：它是模型每一帧都读到的东西，却没有任何机械保障——

- 核对脚本（`tests/_harness_fixtures/node_io.py`）只看 trace 的键名，prompt 它不碰；
- `pytest` 原来全绿也拦不住"把 `子目标（第 N 层）` 前缀加回来"这种事。

而那个前缀是个**真错**：`goals` 是本局那**一个**目标（186 单投，恒一层）
（活跃条目 + 正在跑的那条搬到末位），位次只是"在这份列表里排第几"，
**不是层级**。目标表在 `run_plan` 的 `goals_lines()`
那份**目标表**上。两处都叫"第 N"，指的却是两件不同的事——照 prompt 对 trace
会**静默对错目标**。事故与账见 `CHANGELOG.md` 2026-09-14 第 91/92 条。
"""

from __future__ import annotations

from pokemon_agent.brain.interface import Goal
from pokemon_agent.direct.prompts.decide_action import build_prompt
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.world import ActionSpace, TaskObservation, TaskScene

MARK = "← 你现在要完成的"


def _goal_section(goals: list[Goal]) -> str:
    """拼一次完整的决策 prompt，把「## 目标」那一节切出来。

    走 `build_prompt`（公开入口）而不是直接调渲染 helper：这一节是**拼装产物**，
    要钉的就是"模型最终读到的样子"。
    """
    prompt = build_prompt(
        FromHarnessToBrainToolChooseOnceReq(
            goals=goals,
            obs=TaskObservation(step=0, status="你在野外。", perceived=False, scene=TaskScene.WALK),
            space=ActionSpace(names=["up"], descriptions={"up": "向上走"}),
            memories=[],
        )
    )
    return prompt.split("## 目标", 1)[1].split("## 当前状态", 1)[0]


def _three_goals() -> list[Goal]:
    """表里两条**同层兄弟** + 正在跑的那条（brain 的 plan 一次推 ≥2 条就是这个形状）。

    186 单投后 `goals` 恒一层，`走到草丛` 就是这一局的靶子。
    """
    return [
        Goal(goal="向北走一步看看反应", criteria="坐标变化或有对话框"),
        Goal(goal="找到宝可梦中心", criteria="地图上出现中心"),
        Goal(goal="走到草丛", criteria="进草地"),
    ]


def test_the_goal_this_episode_must_finish_is_marked_and_listed_first() -> None:
    section = _goal_section(_three_goals())

    assert section.index("走到草丛") < section.index("找到宝可梦中心")
    marked = [ln for ln in section.splitlines() if ln.startswith("- ") and MARK in ln]
    assert len(marked) == 1, f"靶子只能有一个，实为 {marked}"
    assert f"- 走到草丛  {MARK}" in section


def test_a_single_goal_renders_as_one_bullet_with_its_criteria() -> None:
    section = _goal_section([Goal(goal="向北走一步看看反应", criteria="坐标变化")])

    assert section.count("- ") == 1
    assert "判据：坐标变化" in section
    assert f"- 向北走一步看看反应  {MARK}" in section


def test_the_goal_list_does_not_pretend_to_be_a_layered_stack() -> None:
    """位次不是层级：不加序号、不加"第 N 层"。

    这条是**形状守卫**——它拦的正是 2026-09-14 删掉的那种写法
    （`0. [任务目标] …` / `1. [子目标（第 1 层）] …`）。同一条目标在两处
    （这里与 `run_plan` 的目标表）被编上号，两个号指的却是不同的东西。
    """
    section = _goal_section(_three_goals())

    assert "层" not in section
    assert "子目标" not in section
    assert "[任务目标]" not in section
    for line in section.splitlines():
        assert not line[:1].isdigit(), f"目标行不该带行首序号：{line!r}"


def test_shop_prompt_lists_only_shop_scripts_and_requests_an_args_object() -> None:
    from pokemon_agent.world import ShopItemsView
    from pokemon_agent.world.scripts.catalog import script_entries

    request = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="买一个精灵球", criteria="背包球数增加一")],
        obs=TaskObservation(
            step=0,
            status="商店菜单",
            scene=TaskScene.SHOP_ITEMS,
            takeover=ShopItemsView(items=[], money=3000, bag=[]),
        ),
        space=ActionSpace(
            names=[],
            entries=script_entries("shop_items"),
            mask={entry.name: True for entry in script_entries("shop_items")},
        ),
        memories=[],
    )

    prompt = build_prompt(request)

    scripts = prompt.split("## 可调用的脚本", 1)[1]
    assert all(name in scripts for name in ("buy_item", "sell_item", "shop_quit"))
    assert "battle_fight" not in scripts and "walk_to" not in scripts
    assert '"args": {' in prompt
    assert "你不直接按键" in prompt


def test_battle_navigation_prompt_exposes_directions_scripts_and_cursor() -> None:
    from pokemon_agent.world import Facts
    from pokemon_agent.world.action_space import compute_action_space

    observation = TaskObservation(
        step=0,
        status="战斗菜单",
        scene=TaskScene.BATTLE_MENU,
        facts=Facts(overlay=Facts.Overlay.CHOICE, cursor="FIGHT", screen="▶FIGHT PKMN\n ITEM RUN"),
    )
    request = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="光标停在 RUN，不确认", criteria="cursor=RUN")],
        obs=observation,
        space=compute_action_space(observation, ["up", "down", "left", "right", "a", "b"]),
        memories=[],
    )

    prompt = build_prompt(request)

    assert all(f"- {key}:" in prompt for key in ("up", "down", "left", "right"))
    assert "battle_run" in prompt
    assert "cursor: FIGHT" in prompt and "▶FIGHT PKMN" in prompt
    assert "你不直接按键" not in prompt
