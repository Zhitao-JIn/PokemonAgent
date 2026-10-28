"""L0 的 plan 与 judge 共用全部局详情，并携带背景、知识和当前画面。"""

from pathlib import Path

from _harness_fixtures.harness import build_fake
from _harness_fixtures.prompt_text import index_text, observation_text
from langgraph.runtime import Runtime

from pokemon_agent.brain import Goal, RunPlan
from pokemon_agent.harness.run.plan_run import plan_run
from pokemon_agent.harness.run.review_and_judge.review_and_judge import review_and_judge
from pokemon_agent.harness.run.run_state import PlanContext, RunState
from pokemon_agent.prompt import JudgeParams, PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import EpisodeOutput, Termination
from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory
from pokemon_agent.world import Facts, TaskObservation, TaskScene


class _Planner:
    def __init__(self) -> None:
        self.requests: list[FromHarnessToBrainToolPlanOnceReq] = []

    def plan(self, req: FromHarnessToBrainToolPlanOnceReq) -> FromHarnessToBrainToolPlanOnceResp:
        self.requests.append(req)
        goal = RunPlan.PlanGoal(
            goal="下一局目标", success_criteria="c", budget={"limit": 2, "unit": "tasks"}
        )
        return FromHarnessToBrainToolPlanOnceResp(
            plan=RunPlan(why="测试规划依据", new_items=[goal]), calls=[ModelCall(payload={})]
        )


class _Judger:
    def __init__(self) -> None:
        self.requests: list[FromHarnessToBrainToolJudgeReq] = []

    def judge(self, req: FromHarnessToBrainToolJudgeReq) -> FromHarnessToBrainToolJudgeResp:
        self.requests.append(req)
        return FromHarnessToBrainToolJudgeResp(
            decision=("achieved" if False else "continue"),
            why="继续",
            calls=[ModelCall(payload={})],
        )


def _state() -> RunState:
    details = [
        EpisodeMemory(
            run_id="r",
            run_goal="总目标",
            episode_id=f"e{i}",
            goal=f"局{i}",
            steps=1,
            summary=f"局{i}首句。局{i}详情第二句。",
            quality_score=0.5,
            quality_rationale="q",
            pointers=[],
            index={"headline": "", "keys": [], "evidence": []},
        )
        for i in range(3)
    ]
    background = RunMemory(
        run_id="past",
        run_goal="另一个目标",
        episodes=2,
        succeeded=1,
        summary="背景首句。背景第二句不该全文出现。",
        quality_score=0.5,
        quality_rationale="q",
        pointers=[],
        index={"headline": "", "keys": [], "evidence": []},
    )
    context = PlanContext(details=details, run_index=[background], knowledge=["知识甲", "知识乙"])
    observation = TaskObservation(
        step=3,
        scene=TaskScene.WALK,
        place={"map_id": 12, "x": 3, "y": 5},
        facts=Facts(overlay="none"),
    )
    outcome = EpisodeOutput(
        episode_id="e2", goal_id="g", termination=Termination.GOAL_DONE, tasks_used=1, acts_used=2
    )
    return RunState(
        run_id="r",
        run_goal=Goal(goal="总目标", criteria="c"),
        goals=[],
        step=3,
        observation=observation,
        plan_ctx=context,
        episode_outputs=[outcome],
    )


def _requests(
    state: RunState, root: Path
) -> tuple[FromHarnessToBrainToolPlanOnceReq, FromHarnessToBrainToolJudgeReq]:
    fake = build_fake(root, checkpoints=False)
    planner, judger = _Planner(), _Judger()
    fake.run_rt.planner, fake.run_rt.judger = planner, judger
    runtime = Runtime(context=fake.run_rt)
    plan_run(state, runtime)
    review_and_judge(state, runtime)
    return planner.requests[0], judger.requests[0]


def test_plan_run_and_run_judge_read_the_same_episode_memories(tmp_path: Path) -> None:
    state = _state()

    plan, judge = _requests(state, tmp_path)

    assert plan.details is judge.episode_memories is state.plan_ctx.details
    assert [memory.episode_id for memory in plan.details] == ["e0", "e1", "e2"]
    assert all(
        left is right for left, right in zip(plan.details, judge.episode_memories, strict=True)
    )


def test_run_judge_request_carries_run_index_knowledge_and_observation(tmp_path: Path) -> None:
    state = _state()

    plan, judge = _requests(state, tmp_path)
    blocks, prompt = memory_blocks(judge), build_prompt(judge)

    assert plan.run_index == judge.run_index == state.plan_ctx.run_index
    assert judge.knowledge == "\n\n".join(plan.knowledge) == "知识甲\n\n知识乙"
    assert plan.observation is judge.observation is state.observation
    assert blocks[-2].startswith("## 过往 run(背景,不是本 run 完成的证据)")
    assert index_text(state.plan_ctx.run_index[0]) in blocks[-2]
    assert "背景第二句" not in prompt
    assert blocks[-1] == "## 当前画面\n" + observation_text(state.observation)
    assert all(f"局{i}详情第二句" in prompt for i in range(3))
    assert judge.knowledge in prompt


def test_run_judge_keeps_the_existing_empty_details_case_without_plan_context(
    tmp_path: Path,
) -> None:
    state = _state().model_copy(update={"plan_ctx": None})
    fake, judger = build_fake(tmp_path, checkpoints=False), _Judger()
    fake.run_rt.judger = judger

    review_and_judge(state, Runtime(context=fake.run_rt))

    request = judger.requests[0]
    assert request.episode_memories == [] and request.run_index == []
    assert request.knowledge == "" and request.observation is state.observation


def build_prompt(req: FromHarnessToBrainToolJudgeReq) -> str:
    """Render the judgement materials through the gateway."""
    return (
        PromptGateway(None)
        .render("judge_success", JudgeParams.model_validate(req.model_dump(mode="json")))
        .text
    )


def memory_blocks(req: FromHarnessToBrainToolJudgeReq) -> list[str]:
    """Keep the independent judgement material blocks and their order."""
    return PromptGateway(None).render_history(
        "judge_success", JudgeParams.model_validate(req.model_dump(mode="json"))
    )
