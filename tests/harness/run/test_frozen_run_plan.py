"""run 层冻结规划（`loop.freeze_run_plan`）的用法示范：**表给什么就派什么，判负即收尾**。

**为什么这个文件值钱**：冻结开关把 `plan_run` 整段退场——不调 planner、不问人审、不写
`plan_call` / `plan_verdict`、不占规划轮数。这四件事没有类型系统保护，改坏了只会表现成
"评测样本的目标被模型悄悄改写"或"该停的时候还在派"。这里钉住：

- 派发顺序等于表序，planner 替身 0 次调用；
- 第一条判负（`FAILED`）后**后面的条目不再派发**，run 以 `FROZEN_ITEM_FAILED` 收尾；
- 表跑完仍未判成功时用现有 `PLANNING_EXHAUSTED` 收尾；
- 开关开着却没给表：入口断言失败，不静默退回自由规划；
- 开关关着：planner 照旧在环里（本文件只做对照，行为由既有用例继续覆盖）。

**用真 run 图 + 假 episode 入口与假世界端**：不碰模拟器、不调模型、落盘根用 `tmp_path`。
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
from _harness_fixtures.app_config import app_config

from pokemon_agent.brain import Goal, RunPlan, Task
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.harness import RunHarness, RunRuntime
from pokemon_agent.harness.episode import episode_entry
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.run import compile_run_graph
from pokemon_agent.harness.run.run_entry import initial_plan
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

RUN_ID = "r-frozen"
RUN_GOAL = Goal(goal="依次走完两步", criteria="两步都走完")


class _Planner:
    """只记调用次数、从不新增目标；冻结开时它一次都不该被叫到。"""

    def __init__(self) -> None:
        self.calls = 0

    def plan(self, req):
        self.calls += 1
        return type(
            "Resp",
            (),
            {"plan": RunPlan(why="替身不新增目标"), "calls": [ModelCall(payload={})]},
        )()


class _Judger:
    """第 `done_on` 次被问时判达成；None = 永不达成。"""

    def __init__(self, done_on: int | None) -> None:
        self._done_on, self.asked = done_on, 0

    def judge(self, req):
        self.asked += 1
        return FromHarnessToBrainToolJudgeResp(
            decision=("achieved" if self.asked == self._done_on else "continue"),
            why="桩",
            calls=[ModelCall(payload={})],
        )


class _Memory:
    """run 图读写的两个口：局摘要、地图事实（本用例都不产生内容）。"""

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
                self.stored.append(
                    EpisodeMemory(
                        **record.payload,
                    )
                )
            stored.append(
                FromHarnessToMemoryToolMemorizedRecord(
                    kind=record.kind, uuid=f"{record.kind}-{len(self.stored)}"
                )
            )
        return FromHarnessToMemoryToolMemorizeResp(stored=stored)


class _Game:
    """世界端桩：reset 记下任务，perceive 回一帧恒定起点画面（不判停）。"""

    def __init__(self) -> None:
        self.reset_tasks: list[Task] = []

    def reset(self, req) -> None:
        self.reset_tasks.append(req.task)

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        return FromHarnessToGameToolPerceiveTaskResp(
            observation=TaskObservation(facts={"overlay": "none"}, step=0, scene=TaskScene.WALK),
            frame_png="F",
        )


def _harness(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    freeze: bool,
    episodes: list[bool],
    planner: _Planner,
    judger: _Judger,
) -> tuple[RunHarness, list[str]]:
    """装配一条 run 级执行线；返回 harness 与逐局派发到的目标 id（按派发序）。"""
    seen: list[str] = []

    def fake_run_episode(deps, graph, *, episode_input):
        seen.append(episode_input.goal.task_id)
        verdict = episodes[len(seen) - 1] if len(seen) <= len(episodes) else True
        return EpisodeOutput(
            episode_id=episode_input.episode_id,
            goal_id=episode_input.goal.task_id,
            termination=Termination.GOAL_DONE if verdict else Termination.BUDGET_EXHAUSTED,
            tasks_used=1,
            acts_used=3,
        )

    monkeypatch.setattr(episode_entry, "run_episode", fake_run_episode)
    trace, memory, game = TraceTool(LocalTrace(root=tmp_path)), _Memory(), _Game()
    deps = RunRuntime(
        config=app_config(
            loop={"freeze_run_plan": freeze},
            budget={"max_episodes": 3, "max_planning_rounds": 2},
        ),
        trace=trace,
        memory=memory,  # type: ignore[arg-type]
        reviewer=NullReviewer(),
        run_summarizer=None,  # type: ignore[arg-type]
        planner=planner,  # type: ignore[arg-type]
        judger=judger,  # type: ignore[arg-type]
        episode_graph=None,  # type: ignore[arg-type]
        episode=SimpleNamespace(memory=memory, trace=trace),  # type: ignore[arg-type]
        game=game,  # type: ignore[arg-type]
    )
    return RunHarness(deps, compile_run_graph()), seen


def _kinds(harness: RunHarness) -> list[str]:
    """本次 run 落盘的全部账 kind（TraceTool 直接构造，没有归属章，故不按 run_id 过滤）。"""
    return [event.kind for event in harness.read_events()]


def _two_goals() -> list[Task]:
    return [
        Task(task_id="g1", goal="走到草丛", success_criteria="进草地", max_steps=3),
        Task(task_id="g2", goal="抓到一只", success_criteria="有宝可梦", max_steps=3),
    ]


def test_a_frozen_table_dispatches_in_table_order_without_asking_the_planner(
    tmp_path, monkeypatch
) -> None:
    """两条目标各派一局、顺序等于表序；planner 零调用，也不写任何规划账。"""
    planner, judger = _Planner(), _Judger(done_on=2)
    harness, seen = _harness(
        tmp_path, monkeypatch, freeze=True, episodes=[True, True], planner=planner, judger=judger
    )

    result = harness.run(RUN_ID, _two_goals(), run_goal=RUN_GOAL)

    kinds = _kinds(harness)
    assert result.termination == Termination.GOAL_DONE
    assert seen == ["g1", "g2"], "派发顺序 = 表序"
    assert planner.calls == 0, "冻结层不调 planner"
    assert "plan_call" not in kinds and "plan_verdict" not in kinds, "冻结层不写规划账"


def test_a_failed_frozen_goal_ends_the_run_before_the_next_entry(tmp_path, monkeypatch) -> None:
    """第一条判负就收尾：后面的条目不再派发，类别是 `frozen_item_failed`。"""
    planner, judger = _Planner(), _Judger(done_on=None)
    harness, seen = _harness(
        tmp_path, monkeypatch, freeze=True, episodes=[False], planner=planner, judger=judger
    )

    result = harness.run(RUN_ID, _two_goals(), run_goal=RUN_GOAL)

    assert seen == ["g1"], "第二条没有被派发"
    assert result.termination == Termination.FROZEN_ITEM_FAILED
    assert result.succeeded == 0 and len(result.outcomes) == 1
    assert planner.calls == 0


def test_a_frozen_table_that_runs_out_ends_at_planning_exhaustion(tmp_path, monkeypatch) -> None:
    """表跑完仍未判成功：用现有 `planning_exhausted` 收尾，不重开、不新增。"""
    planner, judger = _Planner(), _Judger(done_on=None)
    harness, seen = _harness(
        tmp_path, monkeypatch, freeze=True, episodes=[True], planner=planner, judger=judger
    )

    result = harness.run(RUN_ID, _two_goals()[:1], run_goal=RUN_GOAL)

    assert seen == ["g1"]
    assert result.termination == Termination.PLANNING_EXHAUSTED
    assert result.succeeded == 1, "那一局本身跑成了，但 run 没判达成"
    assert planner.calls == 0


def test_an_empty_table_with_the_switch_on_is_a_contract_violation(tmp_path, monkeypatch) -> None:
    """冻结开着却没有表：入口断言失败，不静默退回自由规划。"""
    harness, seen = _harness(
        tmp_path,
        monkeypatch,
        freeze=True,
        episodes=[True],
        planner=_Planner(),
        judger=_Judger(done_on=None),
    )

    with pytest.raises(AssertionError, match="freeze_run_plan"):
        harness.run(RUN_ID, [], run_goal=RUN_GOAL)

    assert seen == []


def test_the_switch_off_leaves_the_planner_in_charge(tmp_path, monkeypatch) -> None:
    """开关关着：即使给了表，规划轮仍照旧问 planner（本文件的对照组）。"""
    planner, judger = _Planner(), _Judger(done_on=None)
    harness, seen = _harness(
        tmp_path, monkeypatch, freeze=False, episodes=[True], planner=planner, judger=judger
    )

    result = harness.run(RUN_ID, _two_goals()[:1], run_goal=RUN_GOAL)

    assert seen == ["g1"]
    assert planner.calls > 0, "开关关着时 planner 仍在环里"
    assert "plan_call" in _kinds(harness)
    assert result.termination == Termination.PLANNING_EXHAUSTED


def test_initial_plan_keeps_every_entry_pending_and_ordered() -> None:
    """`initial_plan` 只包表、不排序也不盖章：表序即派发序，全部 `PENDING`。"""
    entries = initial_plan(_two_goals())

    assert [entry.task.task_id for entry in entries] == ["g1", "g2"]
    assert all(entry.status is EntryStatus.PENDING for entry in entries)
    assert [entry.attempts for entry in entries] == [0, 0]
