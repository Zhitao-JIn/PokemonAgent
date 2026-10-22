"""决策 prompt：脚本条目进 `$actions`。"""

from __future__ import annotations

from pokemon_agent.world import PlaceInWorld, TaskObservation, TaskScene


def _obs(scene: TaskScene) -> TaskObservation:
    return TaskObservation(
        step=0, status="s", scene=scene, place=PlaceInWorld(map_id=12, x=13, y=8)
    )


# ---- 6. 决策 prompt：脚本条目进 $actions ----


def test_decide_prompt_lists_script_entries() -> None:
    from _harness_fixtures.app_config import ACTION_LIMITS
    from prompt.decision_example import build_prompt

    from pokemon_agent.brain.interface import Goal
    from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
    from pokemon_agent.world import ActionEntry, ActionSpace

    space = ActionSpace(
        names=["up"],
        mask={"up": True, "walk_to": True},
        entries=[
            ActionEntry(kind="key", name="up"),
            ActionEntry(
                kind="script",
                name="walk_to",
                params=[
                    __import__("pokemon_agent.world", fromlist=["ScriptParam"]).ScriptParam(
                        name="x", type="int"
                    ),
                    __import__("pokemon_agent.world", fromlist=["ScriptParam"]).ScriptParam(
                        name="y", type="int"
                    ),
                ],
                description="走到本图坐标 (x, y)。",
            ),
        ],
        descriptions={"up": "向上走"},
    )
    prompt = build_prompt(
        FromHarnessToBrainToolChooseOnceReq(
            goals=[Goal(goal="g", criteria="c")],
            obs=_obs(TaskScene.WALK),
            space=space,
            memories=[],
        ),
        max_segments=ACTION_LIMITS.max_segments,
    )
    assert "机械脚本" in prompt
    assert "walk_to(x: int, y: int)" in prompt
    assert "走到本图坐标" in prompt
    assert '{"action": "walk_to", "args"' in prompt  # 输出格式示例
