"""run 总目标与可编辑目标表分离：**空 plan 起步、run goal 由调用方显式传入**（634）。

**为什么这个文件值钱**：这两件事在类型上完全同形（都是文字 + 判据），一旦又被拼成
"同一份数据的两个副本"，planner 合法拆解就会把样本 id 从目标表里抹掉——评测侧于是
按目标 id 找不到局（`knowledge_shop_interaction` 的实际故障）。这里钉住三件事：

- `goals=[]` + 显式 `run_goal` 能跑完，目标由 planner 建，id 是 `plan-<run_id>-1`；
- 空表时世界 reset 用的是按 run goal 合成的引导 `Task`（`max_steps=1`）；
- 旧路径（`goals` 非空、`run_goal` 缺省）行为不变。

**用真 run 图 + 假 episode 入口与假世界端**：不碰模拟器、不调模型、落盘根用 `tmp_path`。
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
from _harness_fixtures.app_config import app_config

from pokemon_agent.brain import Goal, RunPlan, Task
from pokemon_agent.direct.trace import ParsedEvent, TraceTool, parse
from pokemon_agent.direct.trace.content import EpisodeStartContent, RunStartContent
from pokemon_agent.harness import RunHarness, RunRuntime
from pokemon_agent.harness.episode import episode_entry
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.run import compile_run_graph
from pokemon_agent.harness.run.run_entry import start_task_for
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToMemoryToolMemorizedRecord,
    FromHarnessToMemoryToolMemorizeResp,
    FromHarnessToMemoryToolRecallItem,
    FromHarnessToMemoryToolRecallResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import EpisodeOutput, Termination
from pokemon_agent.schemas.memory import EpisodeMemory
from pokemon_agent.trace import LocalTrace
from pokemon_agent.world import TaskObservation, TaskScene

RUN_ID = "r-split"
RUN_GOAL = Goal(goal="和两位不同的 NPC 各说一次话", criteria="两位 NPC 都开过口")


class _Planner:
    """首轮新增 `new_goals` 条目标，之后不再新增；调用次数记在 `calls`。"""

    def __init__(self, new_goals: tuple[str, ...] = ("先和第一位 NPC 说话",)) -> None:
        self._new_goals, self.calls = new_goals, 0

    def plan(self, req):
        self.calls += 1
        items = (
            [
                RunPlan.PlanGoal(
                    goal=goal,
                    success_criteria="对话框开过一次",
                    budget={"limit": 3, "unit": "tasks"},
                )
                for goal in self._new_goals
            ]
            if self.calls == 1
            else []
        )
        return type(
            "Resp",
            (),
            {
                "plan": RunPlan(why="拆出一步可执行的目标", new_items=items),
                "calls": [ModelCall(payload={})],
            },
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
    """世界端桩：记下 reset 收到的 `Task`，perceive 回一帧恒定起点画面（不判停）。"""

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
    planner: _Planner,
    judger: _Judger,
    episodes: list[bool] | None = None,
) -> tuple[RunHarness, _Game]:
    """装配一条 run 级执行线；`episodes` 是逐局的成败脚本（缺省每局成）。"""
    script = list(episodes or [])
    seen: list[str] = []

    def fake_run_episode(deps, graph, *, episode_input):
        # 只桩掉"进图跑"这一段：开局账照写，`episode_start.goal_id` 才与生产同源。
        episode_entry.begin_episode(deps, episode_input)
        seen.append(episode_input.episode_id)
        verdict = script[len(seen) - 1] if len(seen) <= len(script) else True
        return EpisodeOutput(
            episode_id=episode_input.episode_id,
            goal_id=episode_input.goal.task_id,
            termination=Termination.GOAL_DONE if verdict else Termination.BUDGET_EXHAUSTED,
            tasks_used=1,
            acts_used=3,
        )

    monkeypatch.setattr(episode_entry, "run_episode", fake_run_episode)
    trace, memory, game = TraceTool(LocalTrace(root=tmp_path)), _Memory(), _Game()
    config = app_config(budget={"max_episodes": 3, "max_planning_rounds": 2})
    deps = RunRuntime(
        config=config,
        trace=trace,
        memory=memory,  # type: ignore[arg-type]
        reviewer=NullReviewer(),
        run_summarizer=None,  # type: ignore[arg-type]
        planner=planner,  # type: ignore[arg-type]
        judger=judger,  # type: ignore[arg-type]
        episode_graph=None,  # type: ignore[arg-type]
        episode=SimpleNamespace(memory=memory, trace=trace, config=config),  # type: ignore[arg-type]
        game=game,  # type: ignore[arg-type]
    )
    return RunHarness(deps, compile_run_graph()), game


def _events(tmp_path: pathlib.Path) -> list[ParsedEvent]:
    return [parse(event) for event in TraceTool(LocalTrace(root=tmp_path)).read_events()]


def _episode_goal_ids(events: list[ParsedEvent]) -> list[str]:
    return [
        event.content.goal_id
        for event in events
        if event.kind == "episode_start" and isinstance(event.content, EpisodeStartContent)
    ]


def test_an_empty_plan_is_built_by_the_planner_under_the_run_goal(tmp_path, monkeypatch) -> None:
    """空表 + 显式 run goal：planner 建目标、id 是 `plan-<run_id>-1`，表里没有样本 id。"""
    harness, _ = _harness(tmp_path, monkeypatch, planner=_Planner(), judger=_Judger(done_on=1))

    result = harness.run(RUN_ID, [], run_goal=RUN_GOAL, sample_id="knowledge_shop_interaction")

    events = _events(tmp_path)
    assert result.termination == Termination.GOAL_DONE
    assert result.sample_id == "knowledge_shop_interaction"
    assert _episode_goal_ids(events) == [f"plan-{RUN_ID}-1"]
    assert "knowledge_shop_interaction" not in _episode_goal_ids(events)


def test_the_reset_task_is_synthesised_from_the_run_goal_when_the_plan_is_empty(
    tmp_path, monkeypatch
) -> None:
    """空表且没给 `start_task`：reset 用 `start_task_for` 合成的引导 Task（`max_steps=1`）。"""
    harness, game = _harness(tmp_path, monkeypatch, planner=_Planner(), judger=_Judger(done_on=1))

    harness.run(RUN_ID, [], run_goal=RUN_GOAL)

    assert [
        (task.task_id, task.goal, task.success_criteria, task.max_steps)
        for task in game.reset_tasks
    ] == [(RUN_ID, RUN_GOAL.goal, RUN_GOAL.criteria, 1)]


def test_an_explicit_start_task_wins_over_the_synthetic_one(tmp_path, monkeypatch) -> None:
    """给了 `start_task` 就用它——调用方的 `initial_state_hint` 只能从这里进来。"""
    start_task = Task(
        task_id="knowledge_shop_interaction",
        goal="和两位 NPC 说话",
        success_criteria="两人都说过",
        max_steps=12,
        initial_state_hint="站在商店门口",
    )
    harness, game = _harness(tmp_path, monkeypatch, planner=_Planner(), judger=_Judger(done_on=1))

    harness.run(RUN_ID, [], run_goal=RUN_GOAL, start_task=start_task)

    assert game.reset_tasks == [start_task]
    assert _episode_goal_ids(_events(tmp_path)) == [f"plan-{RUN_ID}-1"]


def test_missing_both_a_goal_table_and_a_run_goal_is_a_contract_violation(
    tmp_path, monkeypatch
) -> None:
    """空表又没有 run goal：调用方违约，入口就炸（不自己编一个总目标）。"""
    harness, _ = _harness(tmp_path, monkeypatch, planner=_Planner(), judger=_Judger(done_on=1))

    with pytest.raises(AssertionError, match="explicit run_goal"):
        harness.run(RUN_ID, [])


def test_the_old_path_still_derives_the_run_goal_from_the_table(tmp_path, monkeypatch) -> None:
    """`goals` 非空、`run_goal` 缺省：仍按表文字拼总目标，reset 用表序第一条。"""
    task = Task(task_id="g1", goal="走到草丛", success_criteria="进草地", max_steps=3)
    harness, game = _harness(
        tmp_path, monkeypatch, planner=_Planner(new_goals=()), judger=_Judger(done_on=1)
    )

    result = harness.run(RUN_ID, [task])

    events = _events(tmp_path)
    run_start = next(
        event.content for event in events if isinstance(event.content, RunStartContent)
    )
    assert (run_start.run_goal, run_start.run_criteria) == ("依次完成：走到草丛", "进草地")
    assert run_start.goals == ["走到草丛"]
    assert game.reset_tasks == [task]
    assert _episode_goal_ids(events) == ["g1"]
    assert result.termination == Termination.GOAL_DONE


def test_run_start_renders_and_parses_with_an_empty_goal_table(tmp_path, monkeypatch) -> None:
    """`run_goals=[]` 的 run_start 账：渲染出空数组，解析回来仍是空数组 + run goal 原文。"""
    harness, _ = _harness(tmp_path, monkeypatch, planner=_Planner(), judger=_Judger(done_on=1))

    harness.run(RUN_ID, [], run_goal=RUN_GOAL)

    run_start = next(
        event.content for event in _events(tmp_path) if isinstance(event.content, RunStartContent)
    )
    assert run_start.goals == [] and run_start.success_criteria == []
    assert (run_start.run_goal, run_start.run_criteria) == (RUN_GOAL.goal, RUN_GOAL.criteria)


def test_a_planner_that_never_adds_goals_ends_at_planning_exhaustion(tmp_path, monkeypatch) -> None:
    """首轮无新增：回 `review_and_judge`（`no_pending`）复问，规划轮数耗尽后机械收尾。"""
    planner, judger = _Planner(new_goals=()), _Judger(done_on=None)
    harness, _ = _harness(tmp_path, monkeypatch, planner=planner, judger=judger)

    result = harness.run(RUN_ID, [], run_goal=RUN_GOAL)

    assert result.termination == Termination.PLANNING_EXHAUSTED
    assert result.total == 0, "没有任何目标被派成一局"
    assert _episode_goal_ids(_events(tmp_path)) == []
    assert planner.calls == 2, "两次规划轮各问一次；第三次进 plan_run 时预算已满，不再问模型"
    assert judger.asked == 2, "每次 planner 无新增都回 judge 复问一次"


def test_start_task_for_carries_the_run_goal_with_the_minimal_budget() -> None:
    """合成引导 Task：id 用 run_id、文字取自 run goal、`max_steps` 取世界端口下界 1。"""
    task = start_task_for("r9", Goal(goal="总目标", criteria="总判据"))

    assert (task.task_id, task.goal, task.success_criteria, task.max_steps) == (
        "r9",
        "总目标",
        "总判据",
        1,
    )
    assert task.initial_state_hint == ""
