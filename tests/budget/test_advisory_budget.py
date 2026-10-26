"""父级预算是建议；真实三层图只按配置预算停机，不访问网络。"""

import json
from pathlib import Path

import pytest
from _fake_run import GOAL, build_fake, every, never
from _harness_fixtures.app_config import reconfigure

from pokemon_agent.brain import Goal
from pokemon_agent.harness.task import compile_task_graph
from pokemon_agent.harness.task.task_entry import run_task
from pokemon_agent.schemas.harness.domain import TaskInput, Termination


@pytest.mark.parametrize("advice", [1, 99])
def test_task_can_exceed_parent_advice_but_stops_at_configured_actions(
    tmp_path: Path, advice: int
) -> None:
    fake = build_fake(tmp_path, task=never)
    reconfigure(fake.run_rt, budget={"task_max_steps": 3})
    task_input = TaskInput(
        entry_id="t",
        run_id="r1",
        episode_id="ep",
        total_acts=0,
        task=GOAL.model_copy(update={"goal": "子任务", "max_steps": advice}),
    )

    output = run_task(fake.run_rt.episode.task, compile_task_graph(), task_input=task_input)

    assert output.steps_used == 3
    assert output.termination is Termination.BUDGET_EXHAUSTED
    assert task_input.task.max_steps == advice


@pytest.mark.parametrize("advice", [1, 99])
def test_episode_can_exceed_parent_advice_but_stops_at_configured_tasks(
    tmp_path: Path, advice: int
) -> None:
    fake = build_fake(tmp_path, task=every(1), episode=never, run=never, tasks_per_plan=1)
    reconfigure(fake.run_rt, budget={"max_episodes": 1, "episode_max_tasks": 3})

    output = fake.harness.run("r1", [GOAL.model_copy(update={"max_steps": advice})])

    assert output.outcomes[0].tasks_used == 3
    assert output.outcomes[0].termination is Termination.TASKS_EXHAUSTED


def test_actual_model_prompts_receive_advice_configured_limits_and_remaining(
    tmp_path: Path,
) -> None:
    fake = build_fake(tmp_path, task=every(2), episode=every(2), run=every(1))
    reconfigure(
        fake.run_rt, budget={"max_episodes": 2, "episode_max_tasks": 3, "task_max_steps": 4}
    )

    fake.harness.run("r1", [GOAL.model_copy(update={"max_steps": 1})])

    prompts: dict[str, list[str]] = {}
    for event in fake.trace.read_events({"run_id": "r1"}):
        if event.kind in ("plan_call", "decompose_call", "choose_call"):
            prompts.setdefault(event.kind, []).append(json.loads(event.content)["prompt"])
    for kind in ("decompose_call", "choose_call"):
        assert "父级建议 |" in prompts[kind][0]
        assert "配置硬限 |" in prompts[kind][0]
        assert "来源=parent.budget.limit" in prompts[kind][0]
        assert "已用=" in prompts[kind][0] and "剩余=" in prompts[kind][0]
    assert "单位=tasks | 来源=budget.episode_max_tasks | 额度=3.0" in prompts["decompose_call"][0]
    assert "单位=actions | 来源=budget.task_max_steps | 额度=4.0" in prompts["choose_call"][0]
    assert any("已用=1.0 | 剩余=3.0" in prompt for prompt in prompts["choose_call"])


def test_run_planning_sees_configured_limits_before_creating_child_advice(tmp_path: Path) -> None:
    fake = build_fake(tmp_path, task=every(1), episode=every(1), run=every(1))
    reconfigure(
        fake.run_rt, budget={"max_episodes": 2, "episode_max_tasks": 3, "task_max_steps": 4}
    )

    fake.harness.run("r1", [], run_goal=Goal(goal="依次完成目标", criteria="目标达成"))

    event = next(e for e in fake.trace.read_events({"run_id": "r1"}) if e.kind == "plan_call")
    prompt = json.loads(event.content)["prompt"]
    assert "单位=episodes | 来源=budget.max_episodes | 额度=2.0" in prompt
    assert "单位=tasks | 来源=budget.episode_max_tasks | 额度=3.0" in prompt
    assert "单位=actions | 来源=budget.task_max_steps | 额度=4.0" in prompt
