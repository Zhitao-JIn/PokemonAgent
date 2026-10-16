"""run 图状态机的用法示范：**目标表驱动的派发、盖章、与"只在 review_and_judge 停机"**。

**为什么这个文件值钱**：196 起 run 的停机点只有一个——`review_and_judge`（机械三类 +
问模型）；`plan_run` 不再判停。三条都没有类型系统保护、改坏了只会表现成"图跑不完"：

- 失败目标盖 `FAILED`（终态），**不自动重派**——重试只能是 `plan_run` 的显式重开；
- 连续失败达到 `RUN_STALL_LIMIT` 时机械停机，即使 planner 一直重开；
- 单局抛 `AgentError` 时，error handler 复用 `dispatch` 补出派发增量，
  `review_and_judge` 照常找到那条 `RUNNING` 盖章。

**用真 run 图 + 假 episode 入口**：`episode_entry.run_episode` 换成按脚本回结算的
假件；不碰模拟器、不调模型、落盘根用 `tmp_path`。
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from pokemon_agent.brain import Goal, RunPlan, Task
from pokemon_agent.config import DEFAULT_RUN_BUDGET, RUN_STALL_LIMIT
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.errors import AgentError
from pokemon_agent.harness import RunRuntime
from pokemon_agent.harness.episode import episode_entry
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.run import compile_run_graph
from pokemon_agent.harness.run.run_entry import initial_plan
from pokemon_agent.harness.run.run_state import RunState
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToMemoryToolMemorizedRecord,
    FromHarnessToMemoryToolMemorizeResp,
    FromHarnessToMemoryToolRecallItem,
    FromHarnessToMemoryToolRecallResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, EpisodeOutput, Termination
from pokemon_agent.schemas.memory import EpisodeMemory
from pokemon_agent.trace import LocalTrace
from pokemon_agent.world import TaskObservation, TaskScene


class _Planner:
    """`reopen=True` 时把表里每条 `FAILED` 重开；否则什么都不改。"""

    def __init__(self, reopen: bool = False) -> None:
        self._reopen = reopen

    def plan(self, req):
        updates = [
            RunPlan.PlanUpdate(index=i, status="pending")
            for i, entry in enumerate(req.plan)
            if self._reopen and entry.status is EntryStatus.FAILED
        ]
        return type(
            "Resp", (), {"plan": RunPlan(updates=updates), "calls": [ModelCall(payload={})]}
        )()


class _Judger:
    """第 `done_on` 次被问时判达成；`done_on=None` 永不达成。"""

    def __init__(self, done_on: int | None) -> None:
        self._done_on, self.asked = done_on, 0

    def judge(self, req):
        self.asked += 1
        return FromHarnessToBrainToolJudgeResp(
            done=self.asked == self._done_on, why="桩", calls=[ModelCall(payload={})]
        )


class _Memory:
    """run 图读写的三个口：局摘要（读；整局异常时 `act` 代 episode 补章写）、地图事实（读）。"""

    def __init__(self) -> None:
        self.stored: list = []

    def recall(self, req):
        hits = [
            m
            for m in self.stored
            if all(getattr(m, key, None) == value for key, value in req.conditions.items())
        ]
        items = [
            FromHarnessToMemoryToolRecallItem(
                kind="episode",
                uuid=f"e{i}",
                score=None,
                content=m.markdown,
                payload=m.model_dump(exclude={"markdown"}),
            )
            for i, m in enumerate(hits)
        ]
        return FromHarnessToMemoryToolRecallResp(items=items)

    def memorize(self, req):
        stored = []
        for record in req.records:
            if record.kind == "episode":
                self.stored.append(EpisodeMemory(**record.payload))
            stored.append(
                FromHarnessToMemoryToolMemorizedRecord(
                    kind=record.kind, uuid=f"{record.kind}-{len(self.stored)}"
                )
            )
        return FromHarnessToMemoryToolMemorizeResp(stored=stored)


def _run(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    script: list[bool | str],
    *,
    planner: _Planner,
    judger: _Judger,
) -> tuple[RunState, list[str]]:
    """跑真 run 图；第 i 局按 `script[i]` 回成 / 败 / 抛（`"raise"`），超出脚本按败。"""
    calls: list[str] = []

    def fake_run_episode(deps, graph, *, episode_input):
        calls.append(episode_input.episode_id)
        verdict = script[len(calls) - 1] if len(calls) <= len(script) else False
        if verdict == "raise":
            raise AgentError("桩：这一局炸了")
        return EpisodeOutput(
            episode_id=episode_input.episode_id,
            goal_id=episode_input.goal.task_id,
            termination=Termination.GOAL_DONE if verdict else Termination.BUDGET_EXHAUSTED,
            tasks_used=1,
            acts_used=3,
        )

    monkeypatch.setattr(episode_entry, "run_episode", fake_run_episode)
    trace, memory = TraceTool(LocalTrace(root=tmp_path)), _Memory()
    deps = RunRuntime(
        budget=DEFAULT_RUN_BUDGET.model_copy(update={"max_episodes": 3}),
        trace=trace,
        memory=memory,  # type: ignore[arg-type]
        reviewer=NullReviewer(),
        planner=planner,  # type: ignore[arg-type]
        judger=judger,  # type: ignore[arg-type]
        episode_graph=None,  # type: ignore[arg-type]
        # episode 图被桩掉；`act` 接住整局异常时只用到它的记忆与记账两个口。
        episode=SimpleNamespace(memory=memory, trace=trace),  # type: ignore[arg-type]
        # run 层每圈取帧（`perceive` 的 `sense`）；桩一个恒定画面（done=False，不触发判停）。
        game=SimpleNamespace(  # type: ignore[arg-type]
            perceive_task=lambda: FromHarnessToGameToolPerceiveTaskResp(
                observation=TaskObservation(step=0, status="s", scene=TaskScene.WALK),
                frame_png="F",
            )
        ),
    )
    tasks = [
        Task(task_id="g1", goal="走到草丛", success_criteria="进草地", max_steps=3),
        Task(task_id="g2", goal="抓到一只", success_criteria="有宝可梦", max_steps=3),
    ]
    final = compile_run_graph().invoke(
        RunState(
            run_id="runstate", run_goal=Goal(goal="总", criteria="判"), goals=initial_plan(tasks)
        ),
        {"recursion_limit": 200},
        context=deps,
    )
    return RunState.model_validate(final), calls


def test_a_failed_goal_is_not_dispatched_again(tmp_path, monkeypatch) -> None:
    """一条失败目标只跑一局（盖 `FAILED`），run 由 judge 判达成后停。"""
    final, calls = _run(
        tmp_path, monkeypatch, [True, False], planner=_Planner(), judger=_Judger(done_on=2)
    )

    assert calls == ["runstate-ep1", "runstate-ep2"]
    by_goal = {e.task.task_id: e for e in final.goals}
    assert by_goal["g1"].status is EntryStatus.COMPLETED
    assert by_goal["g2"].status is EntryStatus.FAILED
    assert [e.attempts for e in final.goals] == [1, 1]
    assert final.done and final.success and final.termination is Termination.GOAL_DONE
    assert final.pending_episode is None, "结算被 perceive 收进 outcomes 后清空"


def test_consecutive_failures_stop_the_run_mechanically(tmp_path, monkeypatch) -> None:
    """planner 一直重开失败目标、judge 永不判成——连续失败到上限时机械停机。"""
    final, calls = _run(
        tmp_path, monkeypatch, [], planner=_Planner(reopen=True), judger=_Judger(done_on=None)
    )

    assert len(calls) == RUN_STALL_LIMIT
    assert final.done and not final.success
    assert final.termination is Termination.STALLED
    assert final.fail_streak == RUN_STALL_LIMIT


def test_an_episode_error_is_settled_as_a_failed_outcome(tmp_path, monkeypatch) -> None:
    """单局抛 `AgentError`：`act` 接住。

    补空章、记 `episode_error`、兜成 `ERROR` 结算，review 照常盖章。
    """
    final, calls = _run(
        tmp_path, monkeypatch, ["raise", True], planner=_Planner(), judger=_Judger(done_on=2)
    )

    assert calls == ["runstate-ep1", "runstate-ep2"]
    assert final.episode_outputs[0].termination is Termination.ERROR
    assert final.goals[0].status is EntryStatus.FAILED
    assert final.goals[0].last_episode_id == "runstate-ep1"
    assert final.goals[1].status is EntryStatus.COMPLETED
    kinds = [ev.kind for ev in TraceTool(LocalTrace(root=tmp_path)).read_events()]
    assert kinds.count("episode_error") == 1 and kinds.count("write_episode_memory") == 1
    assert kinds[0] == "run_start" and kinds[-1] == "run_end", "起止账在 begin / run_done"


def test_episode_budget_stops_a_run_even_when_success_resets_the_failure_streak(
    tmp_path, monkeypatch
) -> None:
    """局部成功打断连续失败时，总派局预算仍会结束未达成的 run。"""
    final, calls = _run(
        tmp_path,
        monkeypatch,
        [False, True, False],
        planner=_Planner(reopen=True),
        judger=_Judger(done_on=None),
    )

    assert len(calls) == 3
    assert final.fail_streak < RUN_STALL_LIMIT
    assert final.termination is Termination.BUDGET_EXHAUSTED
    assert final.done and not final.success
    events = TraceTool(LocalTrace(root=tmp_path)).read_events()
    assert events[-1].kind == "run_end"
