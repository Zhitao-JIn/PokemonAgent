"""蒸馏三层的编号全文、布局、状态与额度不丢失。"""

import pytest

from pokemon_agent.prompt import PromptGateway, RunPlanParams

from .distillation_examples import NEW_VERSIONS, examples
from .layout_examples import run_example

TASKS = tuple(NEW_VERSIONS)


def test_run_final_goal_table_matches_run_plan_and_keeps_overturn_reason() -> None:
    material = examples()["summarize_run"]
    gateway = PromptGateway(None)
    text = gateway.render("summarize_run", material).text
    base = run_example().model_dump(mode="json")
    plan = RunPlanParams.model_validate({**base, "plan": material.goals})
    rows = gateway.render_history("run_plan", plan, part="goals")
    feedback = text.split("\n## 状态与反馈\n", 1)[1].split("\n## 预算与进度\n", 1)[0]

    assert rows and all(row in feedback for row in rows)
    assert feedback.index(rows[0]) < feedback.index("### 最近判定")
    assert "（人审推翻）" in feedback and "人审推翻的完整理由。" in feedback
    assert "failed" in feedback and "成功" in text.split("\n## 本层历史\n", 1)[1]


@pytest.mark.parametrize("task", TASKS)
def test_empty_judge_reason_and_goal_table_have_no_placeholder(task: str) -> None:
    updates: dict[str, object] = {"judge_reason": ""}
    if task == "summarize_run":
        updates["goals"] = []
    material = examples()[task].model_copy(update=updates)
    text = PromptGateway(None).render(task, material).text
    feedback = text.split("\n## 状态与反馈\n", 1)[1].split("\n## 预算与进度\n", 1)[0]

    assert "### 最近判定" in feedback and "终止类别：" in feedback
    assert "判定依据：" not in feedback and "（无）" not in text
    assert "（无目标条目）" not in text and "### 目标表最终定案" not in feedback
    for heading in ("检索知识", "背景索引", "地图交互事实", "当前现场", "人类插话"):
        assert f"\n## {heading}\n" not in text


@pytest.mark.parametrize("task", ["summarize_task", "summarize"])
def test_empty_history_omits_the_whole_block(task: str) -> None:
    material = examples()[task].model_copy(update={"entries": []})
    text = PromptGateway(None).render(task, material).text

    assert "\n## 本层历史\n" not in text and "## 第 0 条" not in text


@pytest.mark.parametrize("task", ["summarize_task", "summarize"])
def test_unsuccessful_labels_stay_as_in_the_active_old_versions(task: str) -> None:
    material = examples()[task].model_copy(update={"termination": "stalled", "success": False})
    text = PromptGateway(None).render(task, material).text

    assert ("目标未达成" if task == "summarize_task" else "未能完成") in text
    assert "终止类别：stalled" in text
