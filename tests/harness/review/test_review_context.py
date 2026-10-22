"""快照的互斥表、记忆帧与文本渲染；全部使用内存中的请求。"""

import json
from typing import Literal

import pytest
from _harness_fixtures.prompt_text import index_text
from _review_context import review_context
from pydantic import ValidationError

from pokemon_agent.brain import Goal, Task
from pokemon_agent.reviewer.hub.context import context_sections, context_text
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerInjectReq,
)
from pokemon_agent.schemas.harness.domain import GoalEntry, TaskEntry
from pokemon_agent.schemas.harness.domain.review_context import BrainInput, ReviewContext, frames_of
from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory, TaskMemory
from pokemon_agent.world import TaskObservation, TaskScene

FRAME_A = "data:image/png;base64,AAAA"
FRAME_B = "data:image/png;base64,BBBB"
FRAME_C = "data:image/png;base64,CCCC"


def _episode(identifier: str, first: str | None, last: str | None) -> EpisodeMemory:
    return EpisodeMemory(
        run_id="r1",
        episode_id=identifier,
        goal="局目标",
        steps=1,
        summary=f"{identifier} 摘要",
        markdown=f"{identifier} 全文",
        quality_score=0.5,
        quality_rationale="示例",
        first_frame=first,
        last_frame=last,
    )


def _task(identifier: str, first: str | None, last: str | None) -> TaskMemory:
    return TaskMemory(
        run_id="r1",
        episode_id="ep1",
        task_id=identifier,
        goal="子目标",
        steps_used=1,
        total_acts=1,
        summary=f"{identifier} 全文",
        quality_score=0.5,
        quality_rationale="示例",
        first_frame=first,
        last_frame=last,
    )


def _brain_input(kind: str) -> BrainInput:
    goal = Goal(goal="当前目标", criteria="已到达")
    table_task = Task(task_id="table1", goal="唯一表目标", success_criteria="完成", max_steps=3)
    episodes = [
        _episode("ep1", FRAME_A, FRAME_B),
        _episode("ep2", FRAME_A, FRAME_C),
        _episode("ep3", None, None),
    ]
    tasks = [_task("t1", FRAME_A, FRAME_C), _task("t2", FRAME_A, FRAME_B), _task("t3", None, None)]
    observation = TaskObservation(facts={"overlay": "none"}, step=0, scene=TaskScene.WALK)
    if kind == "plan":
        return FromHarnessToBrainToolPlanOnceReq(
            run_goal=Goal(goal="测试父目标", criteria="测试父验收条件"),
            run_id="r1",
            plan=[GoalEntry(task=table_task)],
            details=episodes,
            max_push=2,
            run_index=[
                RunMemory(
                    run_id="older",
                    run_goal="旧目标",
                    episodes=1,
                    succeeded=1,
                    summary="背景首句。后文",
                    quality_score=0.5,
                    quality_rationale="q",
                )
            ],
        )
    if kind == "decompose":
        return FromHarnessToBrainToolDecomposeReq(
            goal=goal,
            observation=observation,
            task_memories=tasks,
            task_table=[TaskEntry(entry_id=(table_task).task_id, task=table_task, round=1)],
            episode_index=[_episode("older", FRAME_B, FRAME_C)],
            max_tasks=2,
        )
    return FromHarnessToBrainToolJudgeReq(
        goal=goal,
        observation=observation,
        episode_memories=episodes if kind == "judge_run" else [],
        task_memories=tasks if kind == "judge_episode" else [],
        task_table=[]
        if kind == "judge_run"
        else [TaskEntry(entry_id=(table_task).task_id, task=table_task, round=1)],
        episode_index=[] if kind == "judge_run" else [_episode("older", FRAME_B, FRAME_C)],
    )


def _context(kind: str) -> ReviewContext:
    req = _brain_input(kind)
    is_run = kind in {"plan", "judge_run"}
    task = Task(task_id="table1", goal="唯一表目标", success_criteria="完成", max_steps=3)
    return ReviewContext(
        layer="run" if is_run else "episode",
        run_id="r1",
        episode_id="r1" if is_run else "ep1",
        brain_input=req,
        goals=[GoalEntry(task=task)] if is_run else None,
        tasks=None if is_run else [TaskEntry(entry_id=(task).task_id, task=task, round=1)],
        step=4,
        fail_streak=2,
    )


@pytest.mark.parametrize("layer", ["run", "episode"])
def test_review_context_layer_exclusive(layer: Literal["run", "episode"]) -> None:
    ctx = _context("plan" if layer == "run" else "decompose")

    wrong = ctx.model_dump()
    wrong["tasks" if layer == "run" else "goals"] = []
    missing = ctx.model_dump()
    missing["goals" if layer == "run" else "tasks"] = None

    with pytest.raises(ValidationError):
        ReviewContext.model_validate(wrong)
    with pytest.raises(ValidationError):
        ReviewContext.model_validate(missing)
    with pytest.raises(ValidationError):
        ReviewContext.model_validate({**ctx.model_dump(), "layer": "task"})
    assert review_context().tasks == []


@pytest.mark.parametrize("kind", ["plan", "decompose", "judge_run", "judge_episode"])
def test_frames_of_dedups_and_labels(kind: str) -> None:
    req = _brain_input(kind)
    is_run = kind in {"plan", "judge_run"}

    frames = frames_of(req)

    assert frames == [
        ("ep1 首帧" if is_run else "t1 首帧", FRAME_A),
        ("ep1 末帧" if is_run else "t1 末帧", FRAME_B if is_run else FRAME_C),
        ("ep2 末帧" if is_run else "t2 末帧", FRAME_C if is_run else FRAME_B),
    ]


def test_frames_of_keeps_later_unique_frames_and_has_no_image_cap() -> None:
    req = FromHarnessToBrainToolPlanOnceReq(
        run_goal=Goal(goal="测试父目标", criteria="测试父验收条件"),
        run_id="r1",
        plan=[],
        max_push=2,
        details=[_episode(str(i), f"data:image/png;base64,{i}", None) for i in range(25)],
    )

    frames = frames_of(req)

    assert frames == [(f"{i} 首帧", f"data:image/png;base64,{i}") for i in range(25)]


@pytest.mark.parametrize("kind", ["plan", "decompose", "judge_run", "judge_episode"])
def test_render_context_sections_and_dedupe(kind: str) -> None:
    ctx = _context(kind)
    original = ctx.model_dump_json()

    text = "\n\n".join(context_text(ctx, section) for section in context_sections(ctx))

    for section in ("大脑输入", "目标表", "任务表", "计数"):
        assert text.count(f"## {section}") == 1
    assert "data:image" not in text
    assert "base64" not in text
    assert text.count("唯一表目标") == 1
    assert "图 3 张，用 brain-frames 查看" in text
    assert "[frame omitted]" in text
    assert '"step": 4' in text and '"fail_streak": 2' in text
    assert ctx.model_dump_json() == original
    assert ReviewContext.model_validate_json(original).model_dump(mode="json") == ctx.model_dump(
        mode="json"
    )


@pytest.mark.parametrize("kind", ["plan", "decompose", "judge_run", "judge_episode"])
def test_render_context_follows_brain_scope_fields(kind: str) -> None:
    ctx = _context(kind)

    text = "\n\n".join(context_text(ctx, section) for section in context_sections(ctx))

    if kind in {"plan", "judge_run"}:
        assert "ep1 全文" in text and "ep2 全文" in text
    else:
        assert "t1 全文" in text and "t2 全文" in text
        assert index_text(ctx.brain_input.episode_index[0]) in text
        assert "older 全文" not in text
    if kind == "plan":
        assert '"details":' in text
        assert index_text(ctx.brain_input.run_index[0]) in text
        assert '"plan":' not in text
    assert '"task_table":' not in text


@pytest.mark.parametrize(
    "request_model", [FromHarnessToReviewerInjectReq, FromHarnessToReviewerAuditReq]
)
def test_every_reviewer_request_requires_context(request_model: type) -> None:
    assert request_model.model_fields["context"].is_required()
    with pytest.raises(ValidationError, match="context"):
        request_model.model_validate({})


@pytest.mark.parametrize(
    "summary",
    [
        "结束了。后面还有。",
        "",
        "  ",
        "字" * 81 + "。",
        "首句\n后文",
        "3.14",
        "首句！后文",
        "首句\r\n后文",
    ],
)
@pytest.mark.parametrize("termination", ["", "goal_done", "budget_exhausted"])
def test_reviewer_index_lines_are_byte_equal_to_the_memory_methods(
    summary: str, termination: str
) -> None:
    memories = [
        _episode("ep1", None, None),
        _task("t1", None, None),
        RunMemory(
            run_id="r1",
            run_goal="总目标",
            episodes=2,
            succeeded=1,
            summary="样本",
            quality_score=0.5,
            quality_rationale="示例",
        ),
    ]
    memories = [
        item.model_copy(update={"summary": summary, "termination": termination})
        for item in memories
    ]
    req = FromHarnessToBrainToolJudgeReq(
        goal=Goal(goal="当前目标", criteria="已到达"),
        episode_index=[memories[0]],
        task_index=[memories[1]],
        run_index=[memories[2]],
    )
    ctx = ReviewContext(
        layer="task",
        task_id="t1",
        run_id="r1",
        episode_id="ep1",
        brain_input=req,
        step=0,
        fail_streak=0,
    )
    original = req.model_dump_json()

    text = context_sections(ctx)["大脑输入"]
    rendered = json.loads(text.rsplit("\n图 ", 1)[0])

    for field, memory in zip(("episode_index", "task_index", "run_index"), memories, strict=True):
        assert rendered[field] == [index_text(memory)]
    assert req.model_dump_json() == original
