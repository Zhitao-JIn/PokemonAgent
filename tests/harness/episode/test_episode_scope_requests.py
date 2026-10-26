"""L1 规划和判定共享全部 task 详情，其他局只作一行背景。"""

from pathlib import Path

from _harness_fixtures.app_config import reconfigure
from _harness_fixtures.harness import build_fake
from _harness_fixtures.prompt_text import index_text, observation_text
from langgraph.runtime import Runtime

from pokemon_agent.brain import Task
from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.episode.plan_episode.plan_episode import plan_episode
from pokemon_agent.harness.episode.review_and_judge import review_and_judge
from pokemon_agent.prompt import DecomposeParams, JudgeParams, PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import TaskEntry
from pokemon_agent.schemas.memory import EpisodeMemory, TaskMemory
from pokemon_agent.world import TERRAIN_MEANING, Facts, TaskObservation, TaskScene


class _Decomposer:
    def __init__(self) -> None:
        self.requests: list[FromHarnessToBrainToolDecomposeReq] = []

    def decompose(
        self, req: FromHarnessToBrainToolDecomposeReq
    ) -> FromHarnessToBrainToolDecomposeResp:
        self.requests.append(req)
        task = Decomposition.PlannedTask(
            goal="下一任务", success_criteria="c", budget={"limit": 2, "unit": "actions"}
        )
        return FromHarnessToBrainToolDecomposeResp(
            decomposition=Decomposition(why="测试规划依据", new_items=[task]),
            calls=[ModelCall(payload={})],
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


class _RevisingReviewer:
    def __init__(self) -> None:
        self.requests: list[FromHarnessToReviewerInjectReq] = []
        self.replies = ["第一次修改", "第二次修改"]

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        self.requests.append(req)
        return FromHarnessToReviewerInjectResp(text=self.replies.pop(0), by="agent", answered=True)

    def audit(self, _req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        raise AssertionError("plan_episode does not audit judgement")


def _state() -> EpisodeRunState:
    task = TaskMemory(
        run_id="r",
        episode_id="e",
        task_id="t",
        goal="走到门口",
        steps_used=1,
        total_acts=0,
        summary="task 首句。task 第二句仍需完整读取。",
        quality_score=0.5,
        quality_rationale="q",
        first_frame="data:image/png;base64,TASK",
    )
    episode = EpisodeMemory(
        run_id="other",
        run_goal="总目标",
        episode_id="prior",
        goal="前局",
        steps=2,
        summary="前局首句。前局第二句只属于详情。",
        quality_score=0.5,
        quality_rationale="q",
        first_frame="data:image/png;base64,PRIOR",
    )
    observation = TaskObservation(
        scene=TaskScene.WALK,
        step=1,
        place={"map_id": 12, "x": 3, "y": 5},
        facts=Facts(overlay="none"),
    )
    return EpisodeRunState(
        run_id="r",
        run_goal="总目标",
        episode_id="e",
        step=1,
        goal=Task(task_id="g", goal="局目标", success_criteria="c", max_steps=4),
        ep_ctx=EpisodeContext(
            observation=observation,
            task_memories=[task],
            episode_index=[episode],
            knowledge_semantic_memory=["知识甲", "知识乙"],
        ),
    )


def _requests(
    state: EpisodeRunState, root: Path
) -> tuple[FromHarnessToBrainToolDecomposeReq, FromHarnessToBrainToolJudgeReq]:
    fake = build_fake(root, checkpoints=False)
    decomposer, judger = _Decomposer(), _Judger()
    deps = fake.run_rt.episode
    deps.decomposer, deps.judger = decomposer, judger
    runtime = Runtime(context=deps)
    plan_episode(state, runtime)
    review_and_judge(state, runtime)
    return decomposer.requests[0], judger.requests[0]


def test_decompose_context_lists_episode_index_lines_not_full_text(tmp_path: Path) -> None:
    state = _state()
    request, _judge = _requests(state, tmp_path)

    text = "\n".join(context_lines(request))

    assert index_text(state.ep_ctx.episode_index[0]) in text
    assert "前局第二句" not in text and "data:image" not in text
    assert "task 第二句仍需完整读取" in text
    empty = request.model_copy(update={"episode_index": []})
    assert index_text(state.ep_ctx.episode_index[0]) not in "\n".join(context_lines(empty))
    params = DecomposeParams.model_validate(
        {**request.model_dump(mode="json"), "terrain_meanings": TERRAIN_MEANING}
    )
    prompt = PromptGateway(None).render("decompose", params).text
    rules = prompt.split("\n## 本次输入\n", 1)[0]
    assert "背景索引是同目标的过往局，不是本局完成的证据" in rules


def test_agent_revisions_respect_remaining_decomposition_budget(tmp_path: Path) -> None:
    fake = build_fake(tmp_path, checkpoints=False)
    decomposer, reviewer = _Decomposer(), _RevisingReviewer()
    deps = fake.run_rt.episode
    deps.decomposer = decomposer
    deps.reviewer = reviewer
    reconfigure(fake.run_rt, budget={"max_decompositions": 2})

    updates = plan_episode(_state(), Runtime(context=deps))

    assert len(decomposer.requests) == 2
    assert [request.human_note for request in decomposer.requests] == ["", "第一次修改"]
    assert [request.max_agent_rounds for request in reviewer.requests] == [1, 1]
    assert len(updates["tasks"]) == 1
    assert updates["decompositions_used"] == 2


def test_plan_and_judge_at_episode_level_read_the_same_task_memories(tmp_path: Path) -> None:
    state = _state()
    state.ep_ctx.task_memories.append(
        state.ep_ctx.task_memories[0].model_copy(update={"task_id": "t2", "total_acts": 1})
    )

    plan, judge = _requests(state, tmp_path)

    assert plan.task_memories is judge.task_memories is state.ep_ctx.task_memories
    assert len(plan.task_memories) == 2
    assert plan.task_memories == judge.task_memories
    assert all(
        left is right for left, right in zip(plan.task_memories, judge.task_memories, strict=True)
    )
    assert plan.episode_index == judge.episode_index == state.ep_ctx.episode_index


def test_episode_judge_request_carries_knowledge_observation_and_index(tmp_path: Path) -> None:
    state = _state()

    plan, judge = _requests(state, tmp_path)
    blocks, prompt = memory_blocks(judge), build_prompt(judge)

    assert judge.knowledge == "\n\n".join(plan.knowledge) == "知识甲\n\n知识乙"
    assert judge.observation is state.ep_ctx.observation
    assert blocks[-2].startswith("## 同目标的过往局(背景,不是本局完成的证据)")
    assert index_text(state.ep_ctx.episode_index[0]) in blocks[-2]
    assert "前局第二句" not in blocks[-2]
    assert blocks[-1] == "## 当前画面\n" + observation_text(state.ep_ctx.observation)
    assert judge.knowledge in prompt and "地图12 x=3 y=5" in prompt
    assert "task 第二句仍需完整读取" in prompt and "data:image" not in prompt


def test_judge_memory_blocks_keep_the_contractual_order(tmp_path: Path) -> None:
    state = _state()
    _plan, judge = _requests(state, tmp_path)
    task = Task(task_id="t", goal="任务", success_criteria="c", max_steps=1)
    judge = judge.model_copy(
        update={
            "task_table": [TaskEntry(entry_id=(task).task_id, task=task, round=1)],
            "episode_memories": state.ep_ctx.episode_index,
            "task_index": state.ep_ctx.task_memories,
        }
    )

    blocks = memory_blocks(judge)

    headers = [block.split("\n", 1)[0] for block in blocks]
    assert headers[0].startswith("## 本局任务表")
    assert headers[1] == "## task t" and headers[2] == "## 局 prior"
    assert headers[3].startswith("## 本局内此前同目标的 task")
    assert headers[4] == "## 同目标的过往局(背景,不是本局完成的证据)"
    assert headers[5] == "## 当前画面"


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


def context_lines(req: FromHarnessToBrainToolDecomposeReq) -> list[str]:
    """Keep decomposition material blocks and their order."""
    params = DecomposeParams.model_validate(
        {**req.model_dump(mode="json"), "terrain_meanings": TERRAIN_MEANING}
    )
    return PromptGateway(None).render_history("decompose", params)
