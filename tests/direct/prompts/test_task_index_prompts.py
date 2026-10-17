"""同目标 task 索引在键与脚本决策、判定里使用同一行视图。"""

import pytest

from pokemon_agent.brain import Goal
from pokemon_agent.direct.prompts.decide_action import build_prompt as decide_prompt
from pokemon_agent.direct.prompts.judge_success import build_prompt as judge_prompt
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolJudgeReq,
)
from pokemon_agent.schemas.memory import TaskMemory
from pokemon_agent.world import ActionEntry, ActionSpace, TaskObservation, TaskScene


def _memory() -> TaskMemory:
    return TaskMemory(
        run_id="r1",
        episode_id="e1",
        task_id="prior",
        goal="去门口",
        termination="goal_done",
        steps_used=3,
        total_acts=0,
        summary="走到门口。然后转身。",
        quality_score=0.5,
        quality_rationale="q",
    )


def _choose(script: bool, index: list[TaskMemory]) -> FromHarnessToBrainToolChooseOnceReq:
    space = ActionSpace(
        names=[] if script else ["up"],
        entries=[ActionEntry(kind="script", name="advance_dialog")] if script else [],
    )
    return FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="去门口", criteria="c")],
        obs=TaskObservation(step=0, status="s", scene=TaskScene.WALK),
        space=space,
        memories=[],
        task_index=index,
    )


@pytest.mark.parametrize("script", [False, True])
def test_task_index_is_rendered_by_index_line_in_both_prompts(script: bool) -> None:
    memory = _memory()
    choose = _choose(script, [memory])
    judge = FromHarnessToBrainToolJudgeReq(goal=choose.goals[0], task_index=[memory])

    decision, verdict = decide_prompt(choose), judge_prompt(judge)

    assert memory.index_line() in decision and memory.index_line() in verdict
    assert "不能用来断言当前目标已达成" in decision
    assert "背景，不是本 task 完成的证据" in verdict
    empty = decide_prompt(_choose(script, []))
    assert "（本局内没有同目标的此前 task）" in empty
    empty_judge = judge_prompt(FromHarnessToBrainToolJudgeReq(goal=choose.goals[0]))
    assert "## 本局内此前同目标的 task（背景，不是本 task 完成的证据）" not in empty_judge
    assert "（没有检索到相关知识）" in empty_judge


@pytest.mark.parametrize("script", [False, True])
def test_decide_prompt_no_longer_has_the_cross_episode_section(script: bool) -> None:
    req = _choose(script, [])

    prompt = decide_prompt(req)

    assert "跨局摘要记忆" not in prompt
    assert "episode_memories" not in type(req).model_fields
