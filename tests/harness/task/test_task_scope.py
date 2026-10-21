"""L2 生成与判定读取全部历史，并共用目标索引与领域知识。"""

from pathlib import Path
from types import SimpleNamespace

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action, ActionSegment, Task
from pokemon_agent.direct.prompts.judge_success import build_prompt
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.harness.task.plan_task import plan_task
from pokemon_agent.harness.task.review_and_judge import review_and_judge
from pokemon_agent.harness.task.task_state import TaskContext, TaskState
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolChooseOnceResp,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    ModelCall,
)
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import ActionSpace, TaskObservation, TaskScene


class _Chooser:
    def __init__(self) -> None:
        self.requests: list[FromHarnessToBrainToolChooseOnceReq] = []

    def choose(
        self, req: FromHarnessToBrainToolChooseOnceReq
    ) -> FromHarnessToBrainToolChooseOnceResp:
        self.requests.append(req)
        return FromHarnessToBrainToolChooseOnceResp(
            action=Action(sequence=[ActionSegment(name="up")]), calls=[ModelCall(payload={})]
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


def _state() -> TaskState:
    memories = [
        ActMemory(
            episode_id="e1",
            task_id="t1",
            step=index,
            action="up",
            before=ActMemory.Observation(step=index, status=f"before {index}"),
            after=ActMemory.Observation(step=index + 1, status=f"after {index}"),
        )
        for index in range(10)
    ]
    return TaskState(
        entry_id=(Task(task_id="t1", goal="去门口", success_criteria="c", max_steps=12)).task_id,
        run_id="r1",
        episode_id="e1",
        total_acts=0,
        step=10,
        task=Task(task_id="t1", goal="去门口", success_criteria="c", max_steps=12),
        knowledge=["知识一：门需要确认", "知识二：朝向要正确"],
        task_ctx=TaskContext(
            act_memories=memories,
            observation=TaskObservation(step=10, status="当前", scene=TaskScene.WALK),
            action_space=ActionSpace(names=["up"]),
        ),
    )


def _requests(
    state: TaskState, tmp_path: Path
) -> tuple[FromHarnessToBrainToolChooseOnceReq, FromHarnessToBrainToolJudgeReq]:
    chooser, judger = _Chooser(), _Judger()
    runtime = Runtime(
        context=SimpleNamespace(
            chooser=chooser,
            judger=judger,
            trace=TraceTool.build(run_id="r1", trace_root=tmp_path),
            review_layers=("run", "episode"),
        )
    )
    plan_task(state, runtime)
    review_and_judge(state, runtime)
    return chooser.requests[0], judger.requests[0]


def test_plan_task_and_task_judge_read_all_act_memories(tmp_path: Path) -> None:
    state = _state()

    choose, judge = _requests(state, tmp_path)

    assert len(choose.memories) == len(judge.history) == 10
    assert choose.memories == judge.history == state.task_ctx.act_memories
    assert all(left is right for left, right in zip(choose.memories, judge.history, strict=True))
    assert choose.task_index == judge.task_index == state.task_index


def test_judge_prompt_carries_knowledge_for_the_task_layer(tmp_path: Path) -> None:
    state = _state()

    choose, judge = _requests(state, tmp_path)
    prompt = build_prompt(judge)

    assert judge.knowledge == choose.knowledge == "\n\n".join(state.knowledge)
    assert judge.knowledge in prompt
    assert "不能替代历史里的证据，也不能作为目标已完成的依据" in prompt
