"""`plan` 的素材面：**从记忆读，不从 trace 读**——0914 S2 的用法示范。

这个文件钉三件事，都是"读错不会报错、只会让规划变蠢"的地方：

1. **素材是 memory，不是 trace**：`plan` 向 `MemoryToolPort` 要本 run 的
   `episode_memory`（带 `run_id` 条件）与 `object_memory`（不带 `map_id`——
   run 级没有"当前地图"）。原先它读全量事件流，那条路已经断掉。
2. **索引按执行顺序排**：`episode_id` 是 `{run_id}-ep{n}`，**字典序在 n≥10 时会乱**
   （`ep10 < ep2`）。排序键取 `state.episode_outputs`（执行序 append 的机械记录）。
3. **详情按确定性规则预取**：最近 1 局 + 全部失败局；其余只给索引行
   （渐进披露的最小可用形态）。

外加两条权限边界：`updates` 只能写"重开/放弃"（机械事实由 harness 盖章），
以及 **plan 节点把模型方言（表内序号 + `RunPlan`）翻成编排方言（`task_id` +
`GoalEntry`）**——0922 第 184 条撤销 `BrainPlanner` 壳后，这层翻译就是节点自己的活。

最后两条钉**停机不归 plan**（196）：`plan_run` 从不写 `done`；规划完表里没有
`PENDING` 时 fail-fast 抛 `NoGoalToDispatch`，而不是静默收手。

**全部用假依赖**：不碰模拟器、不调模型、不写仓库的 `memory/`。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokemon_agent.brain import Goal, RunPlan, Task
from pokemon_agent.errors import NoGoalToDispatch
from pokemon_agent.harness import RunRuntime
from pokemon_agent.harness.run.perceive import perceive
from pokemon_agent.harness.run.plan_run import plan_run
from pokemon_agent.harness.run.run_state import RunState
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToMemoryToolRecallItem,
    FromHarnessToMemoryToolRecallResp,
    ModelCall,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, EpisodeOutput, GoalEntry, Termination
from pokemon_agent.schemas.memory import EpisodeMemory
from pokemon_agent.world import TaskObservation, TaskScene


def _CALL() -> ModelCall:
    return ModelCall(payload={"prompt": "（规划 prompt）", "raw": "{}", "ok": "true"})


# ---- 假件 ----


class _Memory:
    """记录被问了什么的假 memory——plan 只读它与它的两个读口。"""

    def __init__(self, summaries: list[EpisodeMemory], outcomes: list[str]) -> None:
        self._summaries = summaries
        self._outcomes = outcomes
        self.recall_reqs: list = []

    def recall(self, req):
        self.recall_reqs.append(req)
        items = [
            FromHarnessToMemoryToolRecallItem(
                kind="episode",
                uuid=f"u{i}",
                score=None,
                content=m.markdown,
                payload=m.model_dump(exclude={"markdown"}),
            )
            for i, m in enumerate(self._summaries)
        ]
        return FromHarnessToMemoryToolRecallResp(items=items)


class _Trace:
    def __init__(self) -> None:
        self.reqs: list = []

    def append(self, req):
        self.reqs.append(req)
        return len(self.reqs)


class _Reviewer:
    def inject(self, req):
        from pokemon_agent.schemas.harness import FromHarnessToReviewerInjectResp

        return FromHarnessToReviewerInjectResp(text="", answered=False)


class _BrainTool:
    """假大脑：记下收到的信封，按预设回一份 `RunPlan`。"""

    def __init__(self, run_plan: RunPlan | None = None) -> None:
        self._run_plan = run_plan or RunPlan()
        self.reqs: list = []

    def plan(self, req):
        self.reqs.append(req)
        # `calls`：PlannerOutcome 的 input/output 取自最后一次成功调用的 payload。
        return type("Resp", (), {"plan": self._run_plan, "calls": [_CALL()]})()


class _Runtime:
    def __init__(self, deps: RunRuntime) -> None:
        self.context = deps


def _memory(episode_id: str, success: bool, goal: str = "某目标") -> EpisodeMemory:
    return EpisodeMemory(
        episode_id=episode_id,
        run_id="r1",
        goal=goal,
        termination="goal_done" if success else "stalled",
        steps=5,
        summary=f"{episode_id} 的总结",
        quality_score=0.5,
        quality_rationale="桩",
    )


def _outcome(episode_id: str) -> EpisodeOutput:
    return EpisodeOutput(
        episode_id=episode_id,
        goal_id="g1",
        termination=Termination.GOAL_DONE,
        tasks_used=1,
        acts_used=5,
    )


_RUN_GOAL = Goal(goal="总目标", criteria="判据")


def _entry(task_id: str, status: EntryStatus = EntryStatus.PENDING, note: str = "") -> GoalEntry:
    return GoalEntry(
        task=Task(task_id=task_id, goal=f"目标 {task_id}", success_criteria="判据", max_steps=10),
        status=status,
        note=note,
    )


def _deps(memory: _Memory, planner: _BrainTool) -> RunRuntime:
    """plan 只读 run 侧的 `trace` / `memory` / `reviewer` / `planner`——`episode` 字段
    必须给（`RunRuntime` 必传），但本测试用不到它，造个空壳；`game` 给个恒定画面桩
    （测试直接调 `perceive` 格，`sense` 每圈取帧）。
    """
    return RunRuntime(
        trace=_Trace(),  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
        game=SimpleNamespace(  # type: ignore[arg-type]
            perceive_task=lambda: FromHarnessToGameToolPerceiveTaskResp(
                observation=TaskObservation(step=0, status="s", scene=TaskScene.WALK),
                frame_png="F",
            )
        ),
        reviewer=_Reviewer(),  # type: ignore[arg-type]
        run_summarizer=None,  # type: ignore[arg-type]
        planner=planner,  # type: ignore[arg-type]
        judger=None,  # type: ignore[arg-type]
        episode_graph=None,  # type: ignore[arg-type]
        episode=None,  # type: ignore[arg-type]
    )


def _run_once(
    plan_table: list[GoalEntry],
    summaries: list[EpisodeMemory],
    outcomes: list[str],
    run_plan: RunPlan | None = None,
) -> tuple[dict, RunRuntime, _BrainTool]:
    memory = _Memory(summaries, outcomes)
    planner = _BrainTool(run_plan)
    deps = _deps(memory, planner)
    state = RunState(
        run_id="r1",
        run_goal=_RUN_GOAL,
        goals=plan_table,
        episode_outputs=[_outcome(ep) for ep in outcomes],
    )
    rt = _Runtime(deps)
    # 0923 190：记忆读提格——先跑 perceive，plan_run 只读 state.plan_ctx。
    state = state.model_copy(update=perceive(state, rt))

    got = plan_run(state, rt)

    return got, deps, planner


# ---- 素材来自记忆 ----


def test_plan_asks_memory_for_this_run_and_for_no_particular_map() -> None:
    """素材从记忆里取：摘要限本 run，地图事实**不**按地图筛（run 级没有当前地图）。"""
    memory = _Memory([_memory("r1-ep1", True)], ["r1-ep1"])
    deps = _deps(memory, _BrainTool())

    state = RunState(run_id="r1", run_goal=_RUN_GOAL, goals=[_entry("g1")])
    rt = _Runtime(deps)
    state = state.model_copy(update=perceive(state, rt))
    plan_run(state, rt)

    assert memory.recall_reqs[0].conditions == {"run_id": "r1"}


def test_plan_index_order_is_the_memorys_not_resorted() -> None:
    """索引的顺序是记忆读口给的（按 `episode_id` 自然序，即执行序），plan 原样使用、不再自己排。

    自然序本身（`ep2` < `ep10`）由 `MemoryTool` 负责，见 `test_episode_summary_order.py`。
    """
    summaries = [_memory("r1-ep2", True), _memory("r1-ep10", True)]
    _, deps, planner = _run_once([_entry("g1")], summaries, ["r1-ep2", "r1-ep10"])

    assert [m.episode_id for m in planner.reqs[0].index] == ["r1-ep2", "r1-ep10"]


def test_plan_details_are_latest_run_plus_every_failure() -> None:
    """详情预取：最近 1 局 + 全部失败局；更早的成功局只留索引行。

    两个边界：全成功时**只有最近 1 局**；索引为空时给空列表（首轮规划就是这样）。
    """
    summaries = [
        _memory("r1-ep1", True),
        _memory("r1-ep2", False),
        _memory("r1-ep3", True),
        _memory("r1-ep4", True),
    ]
    outcomes = ["r1-ep1", "r1-ep2", "r1-ep3", "r1-ep4"]
    _, _, planner = _run_once([_entry("g1")], summaries, outcomes)

    req = planner.reqs[0]

    assert [m.episode_id for m in req.index] == outcomes, "索引给全部局"
    assert [m.episode_id for m in req.details] == ["r1-ep2", "r1-ep4"], "详情只给失败局 + 最近一局"

    _, _, all_success = _run_once(
        [_entry("g1")], [_memory("r1-ep1", True), _memory("r1-ep2", True)], ["r1-ep1", "r1-ep2"]
    )
    assert [m.episode_id for m in all_success.reqs[0].details] == ["r1-ep2"], "全成功只给最近一局"

    _, _, first_round = _run_once([_entry("g1")], [], [])
    assert first_round.reqs[0].index == [] and first_round.reqs[0].details == [], (
        "首轮没有任何局，两个列表都是空的"
    )


# ---- 目标表的写入 ----


def test_plan_updates_reopen_and_abandon_existing_entries() -> None:
    """模型能改的只有"重开"与"放弃"两件事，且只改被点名的那条。

    两条容易写错的细节也钉住：**模型没给理由时保留旧理由**（上次失败的原因
    也是信息，不该被一次空 `note` 洗掉）；点名点不到的表内条目只是作废，
    表长不变。（0922 起模型给的是**表内序号**，翻译成 `task_id` 是 plan 节点的活。）
    """
    table = [_entry("g1"), _entry("g2", EntryStatus.FAILED, "上次撞墙")]
    run_plan = RunPlan(
        updates=[
            RunPlan.PlanUpdate(index=1, status="pending", note="换个走法"),
            RunPlan.PlanUpdate(index=9, status="abandoned"),  # 越界：作废
        ]
    )

    got, _, _ = _run_once(table, [], [], run_plan)

    assert got["goals"][0].status is EntryStatus.PENDING, "没被点名的原样不动"
    assert got["goals"][1].status is EntryStatus.PENDING and got["goals"][1].note == "换个走法"
    assert len(got["goals"]) == 2, "点不到的表内条目只是作废，不改表长"

    reopened, _, _ = _run_once(
        [_entry("g3", EntryStatus.FAILED, "保持")],
        [],
        [],
        RunPlan(updates=[RunPlan.PlanUpdate(index=0, status="pending")]),
    )
    assert reopened["goals"][0].note == "保持", "模型没给新理由就留着旧的"


def test_plan_cannot_stamp_machine_facts() -> None:
    """`COMPLETED` 是机械事实（这一局到底成没成），brain 写它必须当场炸。

    正常路径下 `RunPlan.PlanUpdate.status` 的 Literal 根本构造不出这个值——
    所以这里用 `model_construct` 绕过校验，钉的是 plan 节点入口那条 invariant
    （防任何绕过信封校验的路径把机械事实写进表）。
    """
    table = [_entry("g1")]
    forged = RunPlan.model_construct(
        updates=[RunPlan.PlanUpdate.model_construct(index=0, status=EntryStatus.COMPLETED)]
    )

    with pytest.raises(AssertionError, match="盖章"):
        _run_once(table, [], [], forged)


# ---- 模型方言 → 编排方言 ----


def test_plan_translates_indices_into_task_ids() -> None:
    """模型按**序号**指名、按 `PlanGoal` 给新目标；
    翻译成 `task_id` + `GoalEntry` 的是 plan 节点。
    """
    run_plan = RunPlan(
        push_goals=[RunPlan.PlanGoal(goal="去宝可梦中心", success_criteria="体力满", max_steps=20)],
        updates=[RunPlan.PlanUpdate(index=0, status="abandoned", note="门锁着")],
        why="先补状态",
    )
    table = [_entry("seed"), _entry("plan-r1-1", EntryStatus.FAILED)]

    got, deps, planner = _run_once(table, [], [], run_plan)

    assert got["goals"][0].status is EntryStatus.ABANDONED and got["goals"][0].note == "门锁着"
    assert [e.task.task_id for e in got["goals"]] == ["seed", "plan-r1-1", "plan-r1-2"], (
        "新目标接着表里已有的号往下编"
    )
    assert got["goals"][2].status is EntryStatus.PENDING
    assert [e.task.task_id for e in planner.reqs[0].plan] == ["seed", "plan-r1-1"], (
        "目标表原样随信封递下去"
    )
    assert deps.trace.reqs[-1].why == "先补状态"


def test_plan_drops_updates_pointing_outside_the_table() -> None:
    """模型数错行（序号越界）不是异常——那条表态作废，别的照常。"""
    run_plan = RunPlan(updates=[RunPlan.PlanUpdate(index=7, status="abandoned", note="?")])

    got, _, _ = _run_once([_entry("seed")], [], [], run_plan)

    assert [e.task.task_id for e in got["goals"]] == ["seed"], "表长不变、条目原样"


# ---- 停机不归 plan ----


def test_plan_never_writes_done() -> None:
    """表里还有 `PENDING` 时，`plan_run` 只交回表——`done` 只由 `review_and_judge` 写。"""
    got, _, _ = _run_once([_entry("还没做")], [], [], RunPlan())

    assert set(got) == {"goals"}, "plan_run 的增量只有目标表"


def test_no_pending_goal_after_planning_fails_fast() -> None:
    """规划完表里没有 `PENDING`（全部出局、模型也不新增/不重开）→ 抛 `NoGoalToDispatch`。

    这不是"该停了"的信号：run 还没被 `review_and_judge` 判停，却无事可派。
    放弃最后一条活跃目标、又不给新目标，正是这种情形。
    """
    with pytest.raises(NoGoalToDispatch):
        _run_once([_entry("已跑完", EntryStatus.COMPLETED)], [], [], RunPlan())

    with pytest.raises(NoGoalToDispatch):
        _run_once(
            [_entry("做不动了")],
            [],
            [],
            RunPlan(updates=[RunPlan.PlanUpdate(index=0, status="abandoned", note="门锁着")]),
        )


def test_the_plan_verdict_event_carries_the_new_goals() -> None:
    """记账的形状：`PLAN_VERDICT` 一条、`pushed` 是新目标的**描述**（run 级事件，step=0）。"""
    got, deps, _ = _run_once(
        [_entry("a")],
        [],
        [],
        RunPlan(
            push_goals=[
                RunPlan.PlanGoal(goal="目标 plan-r1-1", success_criteria="判据", max_steps=10)
            ],
            why="先铺路",
        ),
    )

    verdict = next(r for r in reversed(deps.trace.reqs) if r.kind.value == "plan_verdict")

    assert verdict.kind.value == "plan_verdict"
    assert verdict.meta["step"] == 0 and verdict.meta["episode_id"] == "r1", (
        "run 级账：episode_id 位放 run_id"
    )
    assert not hasattr(verdict, "done"), "plan_verdict 不带 done（停判不归规划）"
    assert verdict.pushed == ["目标 plan-r1-1"]
    assert [e.task.task_id for e in got["goals"]] == ["a", "plan-r1-1"], "新条目排在表尾"
