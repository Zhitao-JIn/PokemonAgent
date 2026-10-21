"""task 可选复核：默认关闭、判成才问、推翻反馈持久化并传入下一次决策。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from _fake_run import GOAL, build_fake, every
from _harness_fixtures.app_config import app_config, reconfigure
from langgraph.runtime import Runtime
from pydantic import ValidationError

from pokemon_agent.brain import Action, ActionSegment, Task
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.harness.task.plan_task import plan_task
from pokemon_agent.harness.task.review_and_judge import review_and_judge
from pokemon_agent.harness.task.task_state import TaskContext, TaskState
from pokemon_agent.reviewer.hub.context import context_sections, context_text
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import Termination
from pokemon_agent.schemas.harness.domain.review_context import ReviewContext, frames_of
from pokemon_agent.schemas.memory import ActMemory, TaskMemory
from pokemon_agent.world import ActionSpace, TaskObservation, TaskScene


class Reviewer:
    def __init__(self, verdict: AuditVerdict = AuditVerdict.ACCEPT) -> None:
        self.verdict = verdict
        self.requests: list[FromHarnessToReviewerAuditReq] = []
        self.injections: list[FromHarnessToReviewerInjectReq] = []

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        self.injections.append(req)
        return FromHarnessToReviewerInjectResp(text="", answered=True, by="human")

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        self.requests.append(req)
        return FromHarnessToReviewerAuditResp(
            verdict=self.verdict,
            note="还没进门" if self.verdict is AuditVerdict.OVERTURN else "",
            answered=True,
            by="human",
        )


class Judger:
    def __init__(self, done: bool, interrupted: bool = False) -> None:
        self.done, self.interrupted = done, interrupted
        self.requests: list[FromHarnessToBrainToolJudgeReq] = []

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        self.requests.append(req)
        return FromHarnessToBrainToolJudgeResp(
            decision=(
                "achieved" if self.done else "interrupted" if self.interrupted else "continue"
            ),
            why="门口",
            calls=[ModelCall()],
        )


class Chooser:
    def __init__(self) -> None:
        self.requests: list[FromHarnessToBrainToolChooseOnceReq] = []

    def choose(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        self.requests.append(req)
        return FromHarnessToBrainToolChooseOnceResp(
            action=Action(sequence=[ActionSegment(name="up")]), calls=[ModelCall()]
        )


def _state() -> TaskState:
    observation = TaskObservation(step=1, scene=TaskScene.WALK, status="门口")
    history = [
        ActMemory(
            task_id="t1",
            episode_id="ep1",
            step=i,
            action="up",
            before=ActMemory.Observation(step=i, status="前"),
            after=ActMemory.Observation(step=i + 1, status="后"),
            before_frame="data:image/png;base64,A",
            after_frame="data:image/png;base64,B" if i == 1 else None,
        )
        for i in (1, 2)
    ]
    return TaskState(
        entry_id=(Task(task_id="t1", goal="进门", success_criteria="在屋内", max_steps=5)).task_id,
        run_id="r1",
        episode_id="ep1",
        total_acts=0,
        step=2,
        knowledge=["门需要确认"],
        task_index=[
            TaskMemory(
                run_id="r1",
                episode_id="ep1",
                task_id="old",
                goal="进门",
                steps_used=1,
                total_acts=1,
                summary="旧任务首句。背景全文不应展开。",
                quality_score=0.5,
                quality_rationale="示例",
            )
        ],
        task=Task(task_id="t1", goal="进门", success_criteria="在屋内", max_steps=5),
        task_ctx=TaskContext(
            observation=observation,
            action_space=ActionSpace(names=["up"]),
            act_memories=history,
        ),
    )


def _runtime(root: Path, reviewer: Reviewer, judger: Judger) -> Runtime:
    return Runtime(
        context=SimpleNamespace(
            trace=TraceTool.build(run_id="r1", trace_root=root),
            reviewer=reviewer,
            judger=judger,
            chooser=Chooser(),
            config=app_config(review={"layers": ["run", "episode", "task"]}),
        )
    )


def test_task_graph_never_touches_reviewer_by_default(tmp_path: Path) -> None:
    reviewer = Reviewer()
    fake = build_fake(tmp_path, reviewer=reviewer, task=every(1), episode=every(1), run=every(1))

    fake.harness.run("r1", [GOAL])

    assert "task" not in fake.run_rt.episode.task.config.review.layers
    assert fake.run_rt.episode.task.reviewer is reviewer
    assert all(req.context.layer != "task" for req in reviewer.requests)
    assert all(req.context.layer != "task" for req in reviewer.injections)


def test_enabled_task_graph_uses_the_injected_reviewer(tmp_path: Path) -> None:
    reviewer = Reviewer()
    fake = build_fake(tmp_path, reviewer=reviewer, task=every(1), episode=every(1), run=every(1))
    reconfigure(fake.run_rt, review={"layers": ["run", "episode", "task"]})

    fake.harness.run("r1", [GOAL])

    requests = [req for req in reviewer.requests if req.context.layer == "task"]
    assert requests
    assert all(req.context.task_id and req.context.brain_input.history for req in requests)
    assert all(req.context.layer != "task" for req in reviewer.injections)


@pytest.mark.parametrize("done", [False, True])
@pytest.mark.parametrize("verdict", [AuditVerdict.ACCEPT, AuditVerdict.OVERTURN])
def test_task_judge_audit_when_layer_enabled(
    tmp_path: Path, done: bool, verdict: AuditVerdict
) -> None:
    state, reviewer, judger = _state(), Reviewer(verdict), Judger(done)
    runtime = _runtime(tmp_path, reviewer, judger)

    updates = review_and_judge(state, runtime)

    assert len(reviewer.requests) == int(done)
    assert not reviewer.injections
    expected = Termination.GOAL_DONE if done and verdict is AuditVerdict.ACCEPT else None
    assert updates["termination"] is expected
    assert updates["last_judge"].audit is (verdict if done else None)
    events = runtime.context.trace.read_events({"run_id": "r1", "task_id": "t1"})
    assert len([e for e in events if e.kind == "review_audit"]) == int(done)
    if done and verdict is AuditVerdict.OVERTURN:
        assert updates["last_judge"].note == "还没进门"
        restored = TaskState.model_validate_json(state.model_copy(update=updates).model_dump_json())
        plan_task(restored, runtime)
        assert runtime.context.chooser.requests[0].human_note == "还没进门"
        assert "被人推翻" in updates["judge_reason"]


def test_task_review_context_carries_task_judge_req(tmp_path: Path) -> None:
    state, reviewer, judger = _state(), Reviewer(), Judger(True)

    review_and_judge(state, _runtime(tmp_path, reviewer, judger))

    ctx = reviewer.requests[0].context
    assert ctx.layer == "task" and ctx.task_id == "t1"
    assert ctx.goals is None and ctx.tasks is None
    assert ctx.brain_input is judger.requests[0]
    assert ctx.brain_input.history is state.task_ctx.act_memories
    assert ctx.step == state.step + 1 and ctx.fail_streak == state.stall_count
    assert frames_of(ctx.brain_input) == [
        ("t1 第 1 键前帧", "data:image/png;base64,A"),
        ("t1 第 1 键后帧", "data:image/png;base64,B"),
    ]
    text = "\n\n".join(context_text(ctx, section) for section in context_sections(ctx))
    assert "data:image" not in text
    assert "图 2 张，用 brain-frames 查看" in text
    assert ctx.brain_input.task_index[0].index_line() in text
    assert "背景全文不应展开" not in text
    for changes in ({"task_id": None}, {"goals": []}, {"tasks": []}):
        with pytest.raises(ValidationError):
            ReviewContext.model_validate({**ctx.model_dump(), **changes})


@pytest.mark.parametrize("step, done, interrupted", [(0, True, False), (2, False, True)])
def test_zero_step_and_interrupt_do_not_ask_reviewer(
    tmp_path: Path, step: int, done: bool, interrupted: bool
) -> None:
    state, reviewer, judger = _state(), Reviewer(), Judger(done, interrupted)
    state.step = step

    updates = review_and_judge(state, _runtime(tmp_path, reviewer, judger))

    assert not reviewer.requests
    assert updates["termination"] is (Termination.INTERRUPTED if interrupted else None)


def test_overturn_does_not_remove_the_mechanical_budget_boundary(tmp_path: Path) -> None:
    state, reviewer = _state(), Reviewer(AuditVerdict.OVERTURN)
    state.step = state.task.max_steps

    updates = review_and_judge(state, _runtime(tmp_path, reviewer, Judger(True)))

    assert updates["termination"] is Termination.BUDGET_EXHAUSTED


def test_disabled_task_review_retains_the_original_trace(tmp_path: Path) -> None:
    state, reviewer = _state(), Reviewer(AuditVerdict.OVERTURN)
    runtime = _runtime(tmp_path, reviewer, Judger(True))
    runtime.context.config = app_config()

    updates = review_and_judge(state, runtime)

    assert updates == {"termination": Termination.GOAL_DONE, "judge_reason": "门口"}
    assert not reviewer.requests
    events = runtime.context.trace.read_events({"run_id": "r1"})
    assert [e.kind for e in events] == ["judge_call", "judge_verdict"]
    content = json.loads(events[-1].content)
    assert content["audit"] == "" and content["human_note"] == ""
