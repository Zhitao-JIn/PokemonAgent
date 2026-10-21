"""递归规划公开用法：空新增、保留、前置排序与重开执行身份。"""

import pytest
from _harness_fixtures.harness import build_fake
from langgraph.runtime import Runtime

from pokemon_agent.brain import Task
from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.harness.episode.act.dispatch_task import dispatch_task
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.episode.review_and_judge import review_and_judge
from pokemon_agent.harness.planning import apply_planning
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToBrainToolJudgeResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, TaskEntry, Termination
from pokemon_agent.world import Facts, TaskObservation, TaskScene


def entry(identity: str, status: EntryStatus = EntryStatus.PENDING) -> TaskEntry:
    """一个具有稳定身份的逻辑目标。"""
    return TaskEntry(
        entry_id=identity,
        task=Task(task_id=identity, goal="移动到门前", success_criteria="门前站位", max_steps=3),
        status=status,
        round=1,
    )


def test_empty_new_items_preserve_pending_and_allow_an_inserted_prerequisite() -> None:
    original = [entry("old")]
    empty = Decomposition(new_items=[], why="保留原任务")

    table, order = apply_planning(original, [], empty, ["old"])

    assert table == original and order == ["old"]
    proposal = Decomposition(
        new_items=[
            {
                "goal": "修正朝向",
                "success_criteria": "面向门",
                "budget": {"limit": 2, "unit": "actions"},
            }
        ],
        execution_order=["new:0", "existing:0"],
        why="先修正朝向再进入",
    )
    _, order = apply_planning(table, [entry("new")], proposal, order)
    assert order == ["new", "old"]


def test_invalid_updates_reject_the_whole_proposal_without_mutating_the_table() -> None:
    original = [entry("old")]
    proposal = Decomposition(
        updates=[{"index": 8, "status": "abandoned", "note": "无效索引"}], why="错误提案"
    )

    with pytest.raises(ValueError, match="序号"):
        apply_planning(original, [], proposal, [])

    assert original[0].status is EntryStatus.PENDING


def test_reopening_one_logical_task_creates_a_new_execution_id() -> None:
    state = EpisodeRunState(
        run_id="r",
        run_goal="进入建筑",
        episode_id="ep",
        goal=entry("parent").task,
        ep_ctx=EpisodeContext(),
        tasks=[entry("logical")],
        execution_order=["logical"],
    )

    first = dispatch_task(state)
    settled = first["tasks"][0].model_copy(update={"status": EntryStatus.FAILED})
    updated = state.model_copy(update={"tasks": [settled], "step": 1})
    proposal = Decomposition(
        updates=[{"index": 0, "status": "pending", "note": "换路重试"}], why="可纠偏"
    )
    table, order = apply_planning(updated.tasks, [], proposal, ["logical"])
    second = dispatch_task(updated.model_copy(update={"tasks": table, "execution_order": order}))

    assert first["task_input"].entry_id == second["task_input"].entry_id == "logical"
    assert first["task_input"].task.task_id != second["task_input"].task.task_id
    assert second["tasks"][0].attempts == 2


class BlockedJudge:
    """记录零执行无待办复判的实际请求。"""

    def __init__(self) -> None:
        self.request = None

    def judge(self, request):
        self.request = request
        return FromHarnessToBrainToolJudgeResp(
            decision="blocked", why="通行资格缺失，需要上层调整", calls=[ModelCall(payload={})]
        )


def test_zero_execution_rejudgement_sees_latest_empty_plan_and_returns_blocked(tmp_path) -> None:
    fake = build_fake(tmp_path)
    judge = BlockedJudge()
    fake.run_rt.episode.judger = judge
    proposal = Decomposition(why="当前约束下没有可派任务")
    state = EpisodeRunState(
        run_id="r1",
        run_goal="通关",
        episode_id="ep",
        goal=entry("parent").task,
        ep_ctx=EpisodeContext(
            observation=TaskObservation(step=0, status="ok", scene=TaskScene.WALK, facts=Facts())
        ),
        latest_planning=proposal,
        judge_trigger="no_pending",
        decompositions_used=1,
    )

    updates = review_and_judge(state, Runtime(context=fake.run_rt.episode))

    assert updates["termination"] is Termination.BLOCKED
    assert judge.request.latest_planning == proposal
    assert judge.request.trigger == "no_pending"
    assert not state.success


class EmptyDecomposer:
    """正常空规划，不借解析错误触发退出。"""

    def decompose(self, request):
        return FromHarnessToBrainToolDecomposeResp(
            decomposition=Decomposition(why="当前没有合法待办，需要判定员核对现场"),
            calls=[ModelCall(payload={})],
        )


def test_empty_decomposition_closes_the_episode_and_returns_blockage_to_run(tmp_path) -> None:
    fake = build_fake(tmp_path)
    fake.run_rt.episode.decomposer = EmptyDecomposer()
    fake.run_rt.episode.judger = BlockedJudge()
    fake.run_rt.judger = BlockedJudge()
    goal = entry("parent").task

    result = fake.harness.run("r1", [goal])

    assert result.termination == "blocked"
    assert len(result.outcomes) == 1 and result.outcomes[0].termination is Termination.BLOCKED
    assert result.outcomes[0].tasks_used == result.outcomes[0].acts_used == 0
    assert "通行资格" in result.outcomes[0].judge_reason


def test_continue_after_empty_decomposition_stops_at_the_planning_budget(tmp_path) -> None:
    class ContinueJudge:
        def judge(self, request):
            return FromHarnessToBrainToolJudgeResp(
                decision="continue", why="可以有限探索", calls=[ModelCall(payload={})]
            )

    fake = build_fake(tmp_path)
    fake.run_rt.episode.decomposer = EmptyDecomposer()
    fake.run_rt.episode.judger = ContinueJudge()
    fake.run_rt.episode.budget = fake.run_rt.episode.budget.model_copy(
        update={"max_decompositions": 2}
    )
    fake.run_rt.budget = fake.run_rt.budget.model_copy(update={"max_episodes": 1})

    result = fake.harness.run("r1", [entry("parent").task])

    assert result.outcomes[0].termination is Termination.DECOMPOSITIONS_EXHAUSTED
    assert result.outcomes[0].tasks_used == 0
