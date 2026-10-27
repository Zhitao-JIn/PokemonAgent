"""`frozen_tasks` 入口（D11）：样本的 task 表怎么从 `harness.run` 走到那一局的 `EpisodeInput`。

**为什么这个文件值钱**：评测入口只有 `harness.run` 一个口，task 表要挂到**目标表条目**上
（`GoalEntry.frozen_tasks`）再由 run 的 `act` 带进 episode；这条路径上的三个转手
（`initial_plan` → `RunState.goals` → `dispatch`）任何一个改坏了都不会报错，
只会表现成"样本给了 task 表、episode 却还在自由拆"。这里钉住：

- 只有被点名的那条目标带表，键指不到表里的条目 → 断言失败；
- 缺省不传时行为与现状一致（每局 `EpisodeInput.tasks` 为空）；
- 传了就原样进那一局的 `EpisodeInput.tasks`，与 `freeze_episode_plan` 开关无关
  （用不用它是 episode 层的事）。

**用真 run 图 + 假 episode 入口与假世界端**：不碰模拟器、不调模型。
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
from _harness_fixtures.app_config import app_config

from pokemon_agent.brain import Goal, Task
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.harness import RunHarness, RunRuntime
from pokemon_agent.harness.episode import episode_entry
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.run import compile_run_graph
from pokemon_agent.harness.run.run_entry import initial_plan
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToMemoryToolMemorizeResp,
    FromHarnessToMemoryToolRecallResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import EpisodeOutput, Termination
from pokemon_agent.trace import LocalTrace
from pokemon_agent.world import TaskObservation, TaskScene

RUN_ID = "r-entry"
RUN_GOAL = Goal(goal="走完两步", criteria="两步都走完")


class _UnusedPlanner:
    """冻结 run 层时 planner 不该被叫到；被叫到就让用例炸出来。"""

    def plan(self, req):
        raise AssertionError("planner should not be called in this test")


class _Judger:
    def __init__(self, done_on: int = 1) -> None:
        self._done_on, self.asked = done_on, 0

    def judge(self, req) -> FromHarnessToBrainToolJudgeResp:
        self.asked += 1
        return FromHarnessToBrainToolJudgeResp(
            decision=("achieved" if self.asked == self._done_on else "continue"),
            why="桩",
            calls=[ModelCall(payload={})],
        )


class _Memory:
    def recall(self, req) -> FromHarnessToMemoryToolRecallResp:
        return FromHarnessToMemoryToolRecallResp(items=[])

    def memorize(self, req) -> FromHarnessToMemoryToolMemorizeResp:
        return FromHarnessToMemoryToolMemorizeResp(stored=[])


class _Game:
    def reset(self, req) -> None:
        return None

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        return FromHarnessToGameToolPerceiveTaskResp(
            observation=TaskObservation(facts={"overlay": "none"}, step=0, scene=TaskScene.WALK),
            frame_png="F",
        )


def _harness(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> tuple[RunHarness, list]:
    """装配一条 run 级执行线；返回 harness 与逐局的 `EpisodeInput`（按派发序）。"""
    inputs: list = []

    def fake_run_episode(deps, graph, *, episode_input):
        inputs.append(episode_input)
        return EpisodeOutput(
            episode_id=episode_input.episode_id,
            goal_id=episode_input.goal.task_id,
            termination=Termination.GOAL_DONE,
            tasks_used=1,
            acts_used=2,
        )

    monkeypatch.setattr(episode_entry, "run_episode", fake_run_episode)
    trace, memory = TraceTool(LocalTrace(root=tmp_path)), _Memory()
    deps = RunRuntime(
        config=app_config(
            loop={"freeze_run_plan": True},
            budget={"max_episodes": 3, "max_planning_rounds": 2},
        ),
        trace=trace,
        memory=memory,  # type: ignore[arg-type]
        reviewer=NullReviewer(),
        run_summarizer=None,  # type: ignore[arg-type]
        planner=_UnusedPlanner(),  # type: ignore[arg-type]
        judger=_Judger(done_on=1),  # type: ignore[arg-type]
        episode_graph=None,  # type: ignore[arg-type]
        episode=SimpleNamespace(memory=memory, trace=trace),  # type: ignore[arg-type]
        game=_Game(),  # type: ignore[arg-type]
    )
    return RunHarness(deps, compile_run_graph()), inputs


def _goals() -> list[Task]:
    return [
        Task(task_id="g1", goal="走到草丛", success_criteria="进草地", max_steps=3),
        Task(task_id="g2", goal="抓到一只", success_criteria="有宝可梦", max_steps=3),
    ]


def _task(task_id: str, goal: str) -> Task:
    return Task(task_id=task_id, goal=goal, success_criteria=f"{goal}完成", max_steps=2)


def test_initial_plan_attaches_frozen_tasks_to_the_named_goal_only() -> None:
    """只有被点名的那条带表；表序、状态、尝试次数都不受影响。"""
    frozen = _task("t1", "走到草丛")

    entries = initial_plan(_goals(), {"g1": [frozen]})

    assert [entry.frozen_tasks for entry in entries] == [[frozen], []]
    assert [entry.task.task_id for entry in entries] == ["g1", "g2"]


def test_initial_plan_rejects_frozen_tasks_for_goals_outside_the_table() -> None:
    """键必须是表里的目标 `task_id`；指不到就是调用方的 bug。"""
    with pytest.raises(AssertionError, match="outside the table"):
        initial_plan(_goals(), {"g9": [_task("t1", "走到草丛")]})


def test_the_default_keeps_every_episode_task_table_empty(tmp_path, monkeypatch) -> None:
    """不传 `frozen_tasks`：每局的 `EpisodeInput.tasks` 为空，与现状一致。"""
    harness, inputs = _harness(tmp_path, monkeypatch)

    harness.run(RUN_ID, _goals()[:1], run_goal=RUN_GOAL)

    assert [list(episode_input.tasks) for episode_input in inputs] == [[]]


def test_frozen_tasks_reach_the_dispatched_episode(tmp_path, monkeypatch) -> None:
    """传了就原样进那一局的 `EpisodeInput.tasks`（表序保留）。"""
    harness, inputs = _harness(tmp_path, monkeypatch)
    frozen = [_task("t1", "走到草丛"), _task("t2", "抓到一只")]

    harness.run(RUN_ID, _goals()[:1], run_goal=RUN_GOAL, frozen_tasks={"g1": frozen})

    assert [episode_input.goal.task_id for episode_input in inputs] == ["g1"]
    assert inputs[0].tasks == frozen
