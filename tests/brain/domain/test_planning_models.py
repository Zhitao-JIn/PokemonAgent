"""规划/判定链的模型：Decomposition / RunPlan / Goal / VerifyVerdict / EpisodeSummary。

这些模型是 harness 内嵌的"数据形状"，字段约束变动会静默改变"模型输出解析得过不过"。
本文件钉项目自己声明的约束与默认值：必填非空、`max_steps` 为正、`status` 只允许两个
值、`quality_score` 闭区间 [0,1]、可选字段的缺省。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pokemon_agent.brain.interface.domain import (
    Decomposition,
    EpisodeSummary,
    Goal,
    RunPlan,
    VerifyVerdict,
)


def test_a_decomposition_requires_at_least_one_task() -> None:
    with pytest.raises(ValidationError):
        Decomposition(tasks=[])


@pytest.mark.parametrize(
    "task",
    [
        {"goal": "", "success_criteria": "s", "max_steps": 1},
        {"goal": "a", "success_criteria": "", "max_steps": 1},
    ],
)
def test_a_planned_task_requires_a_non_empty_goal_and_success_criteria(task: dict) -> None:
    with pytest.raises(ValidationError):
        Decomposition(tasks=[task])


@pytest.mark.parametrize("max_steps", [0, -1])
def test_a_planned_task_requires_a_positive_max_steps(max_steps: int) -> None:
    with pytest.raises(ValidationError):
        Decomposition(tasks=[{"goal": "a", "success_criteria": "s", "max_steps": max_steps}])


def test_a_decomposition_defaults_why_to_empty() -> None:
    decomposition = Decomposition(tasks=[{"goal": "a", "success_criteria": "s", "max_steps": 1}])

    assert decomposition.why == ""


def test_a_run_plan_may_be_empty() -> None:
    plan = RunPlan()

    assert plan.push_goals == []
    assert plan.updates == []
    assert plan.why == ""


@pytest.mark.parametrize(
    "goal",
    [
        {"goal": "", "success_criteria": "s", "max_steps": 1},
        {"goal": "a", "success_criteria": "", "max_steps": 1},
        {"goal": "a", "success_criteria": "s", "max_steps": 0},
    ],
)
def test_a_plan_goal_requires_non_empty_fields_and_a_positive_max_steps(goal: dict) -> None:
    with pytest.raises(ValidationError):
        RunPlan(push_goals=[goal])


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_a_plan_update_status_is_limited_to_pending_or_abandoned(status: str) -> None:
    with pytest.raises(ValidationError):
        RunPlan(updates=[{"index": 0, "status": status}])


def test_a_plan_update_index_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        RunPlan(updates=[{"index": -1, "status": "pending"}])


def test_a_plan_update_note_defaults_to_empty() -> None:
    plan = RunPlan(updates=[{"index": 0, "status": "pending"}])

    assert plan.updates[0].note == ""


@pytest.mark.parametrize(
    "kwargs",
    [{"goal": "", "criteria": "c"}, {"goal": "g", "criteria": ""}],
)
def test_a_goal_requires_a_non_empty_goal_and_criteria(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        Goal(**kwargs)


def test_a_verify_verdict_index_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        VerifyVerdict(index=-1, positive=True, why="w")


@pytest.mark.parametrize(
    ("score", "valid"),
    [(0.0, True), (1.0, True), (1.5, False), (-0.1, False)],
)
def test_quality_score_accepts_the_bounds_and_rejects_outside(score: float, valid: bool) -> None:
    if valid:
        summary = EpisodeSummary(summary="s", quality_score=score, quality_rationale="q")
        assert summary.quality_score == score
    else:
        with pytest.raises(ValidationError):
            EpisodeSummary(summary="s", quality_score=score, quality_rationale="q")


def test_episode_summary_defaults_its_optional_fields() -> None:
    summary = EpisodeSummary(summary="s", quality_score=0.5, quality_rationale="q")

    assert summary.reason == ""
    assert summary.markdown == ""
    assert summary.reusable_patterns == []
    assert summary.critical_decisions == []
    assert summary.failure_points == []
    assert summary.applicable_scenes == []
    assert summary.tags == []


def test_a_task_with_a_positive_max_steps_is_accepted() -> None:
    """`max_steps=1` 是合法下界。"""

    from pokemon_agent.brain.interface.domain import Task

    task = Task(task_id="t1", goal="g", success_criteria="s", max_steps=1)

    assert task.max_steps == 1
