"""episode 层冻结任务表（`loop.freeze_episode_plan`）的用法示范：**表给什么就派什么，判负即收尾**。

**为什么这个文件值钱**：冻结开关让 `plan_episode` 整段退场——不调 decomposer、不问人审、
不写 `decompose_call` / `decompose_verdict`、不占 `decompositions_used`；任务表由
`begin_episode` 按样本给的顺序装好（`round=1`、全 `PENDING`）并自己给出 `execution_order`。
这些都没有类型系统保护，改坏了只会表现成"评测样本的 task 被模型悄悄改写"。这里钉住：

- 派发顺序等于表序，decomposer 替身 0 次调用；
- 第一个 task 判负（`FAILED`）后**后面的 task 不再派发**，本局以 `FROZEN_ITEM_FAILED` 收尾；
- 表跑完仍未判成功时用现有 `DECOMPOSITIONS_EXHAUSTED` 收尾；
- 开关开着却没给表：`begin_episode` 断言失败；表里 `task_id` 重复同样断言失败；
- 开关关着：`tasks` 被忽略（初始表为空、仍由 decomposer 自由拆解）。

**用真 episode 图 + 假 task 入口、假 decomposer、假世界/记忆**：不碰模拟器、不调模型。
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
from _harness_fixtures.app_config import app_config

import pokemon_agent.harness.episode.act as episode_act
from pokemon_agent.brain import Task
from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.harness.episode import compile_episode_graph, episode_entry
from pokemon_agent.harness.episode.episode_runtime import EpisodeRuntime
from pokemon_agent.harness.episode.episode_state import EpisodeRunState
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToMemoryToolMemorizeResp,
    FromHarnessToMemoryToolRecallResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import (
    EntryStatus,
    EpisodeInput,
    TaskOutput,
    Termination,
)
from pokemon_agent.trace import LocalTrace
from pokemon_agent.world import TaskObservation, TaskScene


class _Decomposer:
    """手写替身：只记调用次数，冻结开时它一次都不该被叫到。"""

    def __init__(self) -> None:
        self.calls = 0

    def decompose(
        self, req: FromHarnessToBrainToolDecomposeReq
    ) -> FromHarnessToBrainToolDecomposeResp:
        self.calls += 1
        planned = Decomposition.PlannedTask(
            goal="替身拆出来的任务",
            success_criteria="替身判据",
            budget={"limit": 2, "unit": "actions"},
        )
        return FromHarnessToBrainToolDecomposeResp(
            decomposition=Decomposition(why="替身拆解", new_items=[planned]),
            calls=[ModelCall(payload={})],
        )


class _Judger:
    """第 `done_on` 次被问时判达成；None = 永不达成。"""

    def __init__(self, done_on: int | None) -> None:
        self._done_on, self.asked = done_on, 0

    def judge(self, req) -> FromHarnessToBrainToolJudgeResp:
        self.asked += 1
        return FromHarnessToBrainToolJudgeResp(
            decision=("achieved" if self.asked == self._done_on else "continue"),
            why="桩",
            calls=[ModelCall(payload={})],
        )


class _Memory:
    """只满足 episode 层读写的两个口：检索恒空、写入照单收下。"""

    def __init__(self) -> None:
        self.stored: list = []

    def recall(self, req) -> FromHarnessToMemoryToolRecallResp:
        return FromHarnessToMemoryToolRecallResp(items=[])

    def memorize(self, req) -> FromHarnessToMemoryToolMemorizeResp:
        self.stored.extend(req.records)
        return FromHarnessToMemoryToolMemorizeResp(stored=[])


class _Game:
    """世界端桩：perceive 回一帧恒定起点画面（不判停）。"""

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        return FromHarnessToGameToolPerceiveTaskResp(
            observation=TaskObservation(facts={"overlay": "none"}, step=0, scene=TaskScene.WALK),
            frame_png="F",
        )


def _runtime(
    tmp_path: pathlib.Path, *, freeze: bool, decomposer: _Decomposer, judger: _Judger
) -> EpisodeRuntime:
    return EpisodeRuntime(
        game=_Game(),  # type: ignore[arg-type]
        memory=_Memory(),  # type: ignore[arg-type]
        decomposer=decomposer,  # type: ignore[arg-type]
        judger=judger,  # type: ignore[arg-type]
        summarizer=None,  # type: ignore[arg-type]
        # 假 task 入口不产 TaskMemory，收尾走 leave_chapter（补空章不调蒸馏）。
        trace=TraceTool(LocalTrace(root=tmp_path)),
        reviewer=NullReviewer(),
        task_graph=None,  # type: ignore[arg-type]
        config=app_config(loop={"freeze_episode_plan": freeze}, budget={"episode_max_tasks": 6}),
        task=SimpleNamespace(),  # type: ignore[arg-type]
    )


def _episode_input(tasks: list[Task]) -> EpisodeInput:
    return EpisodeInput(
        run_id="r1",
        run_goal="总目标",
        episode_id="r1-ep1",
        goal=Task(task_id="g1", goal="本局目标", success_criteria="做完", max_steps=3),
        tasks=tasks,
    )


def _task(task_id: str, goal: str) -> Task:
    return Task(task_id=task_id, goal=goal, success_criteria=f"{goal}完成", max_steps=2)


def _run_graph(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    freeze: bool,
    tasks: list[Task],
    script: list[bool],
    judger: _Judger,
    decomposer: _Decomposer | None = None,
) -> tuple[EpisodeRunState, list[str]]:
    """跑真 episode 图；第 i 个 task 按 `script[i]` 回成 / 败（超出脚本按成）。"""
    calls: list[str] = []

    def fake_run_task(deps, graph, *, task_input):
        calls.append(task_input.entry_id)
        ok = script[len(calls) - 1] if len(calls) <= len(script) else True
        return TaskOutput(
            entry_id=task_input.entry_id,
            task_id=task_input.task.task_id,
            termination=Termination.GOAL_DONE if ok else Termination.TASKS_EXHAUSTED,
            steps_used=2,
        )

    monkeypatch.setattr(episode_act, "run_task", fake_run_task)
    deps = _runtime(tmp_path, freeze=freeze, decomposer=decomposer or _Decomposer(), judger=judger)
    state = episode_entry.begin_episode(deps, _episode_input(tasks))
    final = compile_episode_graph().invoke(state, {"recursion_limit": 200}, context=deps)
    return EpisodeRunState.model_validate(final), calls


def _kinds(tmp_path: pathlib.Path) -> list[str]:
    return [event.kind for event in TraceTool(LocalTrace(root=tmp_path)).read_events()]


def test_a_frozen_task_table_runs_in_order_without_asking_the_decomposer(
    tmp_path, monkeypatch
) -> None:
    """两个 task 各派一次、顺序等于表序；decomposer 零调用，也不写拆解账。"""
    decomposer, judger = _Decomposer(), _Judger(done_on=2)

    final, calls = _run_graph(
        tmp_path,
        monkeypatch,
        freeze=True,
        tasks=[_task("t1", "走到草丛"), _task("t2", "抓到一只")],
        script=[True, True],
        judger=judger,
        decomposer=decomposer,
    )

    kinds = _kinds(tmp_path)
    assert final.termination is Termination.GOAL_DONE
    assert calls == ["t1", "t2"], "派发顺序 = 表序"
    assert decomposer.calls == 0, "冻结层不调 decomposer"
    assert "decompose_call" not in kinds and "decompose_verdict" not in kinds


def test_a_failed_frozen_task_ends_the_episode_before_the_next_one(tmp_path, monkeypatch) -> None:
    """第一个 task 判负就收尾：后面的 task 不再派发，类别是 `frozen_item_failed`。"""
    decomposer = _Decomposer()

    final, calls = _run_graph(
        tmp_path,
        monkeypatch,
        freeze=True,
        tasks=[_task("t1", "走到草丛"), _task("t2", "抓到一只")],
        script=[False],
        judger=_Judger(done_on=None),
        decomposer=decomposer,
    )

    assert calls == ["t1"], "第二个 task 没有被派发"
    assert final.termination is Termination.FROZEN_ITEM_FAILED
    assert [entry.status for entry in final.tasks] == [
        EntryStatus.FAILED,
        EntryStatus.PENDING,
    ]
    assert decomposer.calls == 0


def test_a_frozen_task_table_that_runs_out_ends_at_decomposition_exhaustion(
    tmp_path, monkeypatch
) -> None:
    """表跑完仍未判成功：用现有 `decompositions_exhausted` 收尾，不重开、不新增。"""
    decomposer = _Decomposer()

    final, calls = _run_graph(
        tmp_path,
        monkeypatch,
        freeze=True,
        tasks=[_task("t1", "走到草丛")],
        script=[True],
        judger=_Judger(done_on=None),
        decomposer=decomposer,
    )

    assert calls == ["t1"]
    assert final.termination is Termination.DECOMPOSITIONS_EXHAUSTED
    assert decomposer.calls == 0


def test_an_empty_table_with_the_switch_on_is_a_contract_violation(tmp_path) -> None:
    """冻结开着却没有表：入口断言失败，不静默退回自由规划。"""
    deps = _runtime(tmp_path, freeze=True, decomposer=_Decomposer(), judger=_Judger(done_on=None))

    with pytest.raises(AssertionError, match="freeze_episode_plan"):
        episode_entry.begin_episode(deps, _episode_input([]))


def test_duplicate_frozen_task_ids_are_a_contract_violation(tmp_path) -> None:
    """同一局内 `task_id` 必须唯一（它同时是 `TaskEntry.entry_id`）。"""
    deps = _runtime(tmp_path, freeze=True, decomposer=_Decomposer(), judger=_Judger(done_on=None))

    with pytest.raises(AssertionError, match="unique"):
        episode_entry.begin_episode(
            deps, _episode_input([_task("t1", "走到草丛"), _task("t1", "抓到一只")])
        )


def test_begin_episode_installs_the_frozen_table_in_order(tmp_path) -> None:
    """初始任务表：每条 `round=1`、`PENDING`，`entry_id` 取样本的 `task_id`，顺序即表序。"""
    deps = _runtime(tmp_path, freeze=True, decomposer=_Decomposer(), judger=_Judger(done_on=None))

    state = episode_entry.begin_episode(
        deps, _episode_input([_task("t1", "走到草丛"), _task("t2", "抓到一只")])
    )

    assert [entry.entry_id for entry in state.tasks] == ["t1", "t2"]
    assert [entry.round for entry in state.tasks] == [1, 1]
    assert all(entry.status is EntryStatus.PENDING for entry in state.tasks)
    assert state.execution_order == ["t1", "t2"]


def test_the_switch_off_ignores_a_frozen_table(tmp_path, monkeypatch) -> None:
    """开关关着：表不被使用（初始表为空），任务仍由 decomposer 自由拆解。"""
    decomposer, judger = _Decomposer(), _Judger(done_on=1)
    deps = _runtime(tmp_path, freeze=False, decomposer=decomposer, judger=judger)

    state = episode_entry.begin_episode(
        deps, _episode_input([_task("t1", "走到草丛"), _task("t2", "抓到一只")])
    )

    assert state.tasks == [] and state.execution_order == [], "关着时 tasks 被忽略"

    final, calls = _run_graph(
        tmp_path,
        monkeypatch,
        freeze=False,
        tasks=[_task("t1", "走到草丛")],
        script=[True],
        judger=judger,
        decomposer=decomposer,
    )
    assert decomposer.calls == 1, "自由规划仍问 decomposer"
    assert calls == ["g1-t1"], "派的是 decomposer 拆出来的 task，不是样本表里的 t1"
    assert final.termination is Termination.GOAL_DONE
