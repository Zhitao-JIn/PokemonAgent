"""run 图的**图外侧门**：一个 run 的开局与恢复（`new_run` / `resume_run`）。

和图内节点的分工，跟 `episode/episode_entry.py` 与它那些节点的分工是同一个意思：
**凡是"在进图之前必须先做完、且做完才有一个完整初值"的事，都住图外**。run 侧这两件是

- `new_run`：写 `RUN_START` → 造初始 `RunState` → 进图 → 取结算（异常路径补 `RUN_ERROR`）；
- `resume_run`：读 checkpoint 锚点 → 重建 `RunState` → `DataCenter.rebuild` → 进图 →
  补 `CHECKPOINT_RESTORE` → 取结算。

两条都在同一段 `try` 语义下：异常时补一条 `RUN_ERROR` 再原样抛，**不吞**
（跟 `episode_entry` 对 `EPISODE_ERROR` 的处理是同一个模式）。

**`recursion_limit` 的常量也住这里**（`RUN_RECURSION_LIMIT`）：`_invoke()` 是它唯一的
读者（`new_run` / `resume_run` 都从那里进图），所以常量跟着它走（D8-②）。它是 run 级的
**闸门**而不是预算——贴身的限在内层 `episode_entry.episode_budget()`（按剩余步数逐局算），
两层的分工与来龙去脉见那个常量自己的 docstring。

**函数名与 `episode_entry` 刻意不同**：那边是 `run_new`/`run_resume`（"run 起一局"），
这里是 `new_run`/`resume_run`（"起一个 run"）。两个模块各有各的 `run` 语义，同名会
让 `grep run_new` 撞出两处、而它们在不同的层级上——命名规则见
`PLAN_graph_composition.md` §5.3-5（`basename` 要能单独说清身份）的同一条判据。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import Task
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendReq,
    FromHarnessToTraceToolReadDiskEventsReq,
    FromRunHarnessToEpisodeHarnessRunResp,
    RunResp,
)
from pokemon_agent.trace import TraceKind

from ..deps import HarnessDeps
from ..episode.episode_state import EpisodeCheckpoint
from .run_state import ResumeEpisode, RunState

RUN_RECURSION_LIMIT = 200_000
"""run 图的 superstep 闸门——**一个大数，不是预算**。

run 图只有 6 格（`begin` / `plan` / `dispatch` / `episode` / `reflect` / `review`），
每轮派发烧掉个位数 superstep——它该跑多少**没有业务语义可算**，也不必算：真正贴身的
限在内层，`episode_entry.episode_budget()` 按"剩余步数 × 17 + 20"**逐局**算，那才是
"这一局能不能跑完"的守护。

所以这里只留一个**可调的闸门**，唯一用途是"run 图万一不收敛时，别让进程无限跑下去"。
想收紧失控时长（少烧几次 `plan` 的模型调用）就调小，想放宽就调大——**run 级一个大数、
episode 级一个按局算的数（现在也可以是大数）**，两层各留一个能改的常量。

**历史：为什么不再是一项公式。** 它曾是三项之和（run 自己的节点 + Σ episode 内部步数
+ `MAX_PLAN_PUSH` 给的压栈余量），那是 **F5**"子图步数计入父 limit"时代的产物。
**探针 X5** 实测本仓是**形态 B**（`run/episode.py` 调 `episode_entry.run_new` /
`run_resume`，由后者 `graph.invoke` 起子图——父子各算各的计数：父 limit=3 时子图照跑完），
Σ 那一笔是**纯余量**——留着它只会把闸门抬到 20 万量级，却对"run 图失控"毫无守护作用。
拍板结果是把那个量级**显式写成一个常量**：既保留"run 级不设贴身上限"的意图，
又留一个一眼能改的旋钮。几个候选的对照见 `CHANGELOG.md` (33)。
"""


def exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照——run_error 的 req 的 error 字段只吃文本，
    Exception 对象进不了 Pydantic req。

    与 `episode_entry.exc_snapshot` 同形：两个模块各写各的（各自只有一个读者，
    都在自己的 `try` 里），不为省三行跨层 import 一个"共用件"。
    """
    return f"{type(exc).__name__}: {exc}"


def new_run(
    deps: HarnessDeps, graph: CompiledStateGraph, *, run_id: str, goals: list[Task]
) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
    """跑完一个 run：目标栈逐个解决（每层一个 episode），返回 run 级结算。

    返回 `(outcomes, total, succeeded, success_rate)` 四个裸值，不打包成对象——
    trace 里那条 RUN_END 内嵌的 `RunResp` 由 `close()` 自己组装，跟返回值无关。

    `goals` 是初始目标栈，栈顶（最后一个）先解决；`plan` 每轮读历史决定
    压不压新目标；失败的目标由 `reflect` 在重试预算内自动重试，预算耗尽交
    人工。结算由 `reflect` 累积在 `outcomes`，这里组装汇总。

    后置条件：trace 里恰好多一条 RUN_START 和一条 RUN_END——异常路径也
    补齐 RUN_END（error 变体）后原样抛出，不吞（跟 `episode_entry.run_new`
    对 EPISODE_START/EPISODE_END 的处理是同一个模式）。
    """
    assert run_id, "new_run() got an empty run_id"
    assert goals, "new_run() got an empty goal stack"

    # 步骤 1：开局账——RUN_START（跟 `episode_entry.begin_episode` 的 EPISODE_START
    # 是同一个理由：没有它，replay/统计分不出一个 run 从哪开始）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RUN_START,
            step=0,
            episode_id=run_id,
            run_goals=goals,
        )
    )

    state = RunState(run_id=run_id, goals=list(goals), attempts=[0] * len(goals))
    # `deps.run_id` 与这一次 run 的 trace/截图路径同生同死：子侧的 `run_id` 读的就是它。
    deps.run_id = run_id
    try:
        final = _invoke(deps, graph, state)
    except Exception as exc:
        # 步骤 2：异常路径——补 RUN_END（error 变体）再原样抛出，不吞。
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RUN_ERROR,
                episode_id=run_id,
                step=0,
                error=exc_snapshot(exc),
            )
        )
        raise
    return close(deps, final, run_id)


def resume_run(
    deps: HarnessDeps, graph: CompiledStateGraph, *, run_id: str, episode_id: str, step: int
) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
    """恢复入口：三元组 `(run_id, episode_id, step)` 定位（PLAN_checkpoint §4）。

    - step > 0：恢复到该局第 step 步开局，跑完本局后 run 图从 reflect 继续
      （START 条件边按 `resume_episode` 路由，dispatch 走 resume 分支）；
    - step = 0：本局从头重跑（等价于 episode 级恢复的 run 级包装）；
    - 废弃时间线（该步之后的事件/记忆/截图/未来局）由 episode 级
      `resume()` 内的 `void_after` 归档截断。

    前置条件：`deps.checkpoint_root` 非空（装配时注入了存档根目录）；
    `(run_id, episode_id, step)` 三元组指定的那份存档存在——它同时带 run 级与 episode
    级两份状态（见 `episode_state.EpisodeCheckpoint` 落盘布局说明），这里只取 run 级那份。

    run 级的 `checkpoint_restore` 标记事件在 `graph.invoke()` **之后**才
    append（顺序本身是契约的一部分，别挪到前面）——原因见下面那段注释。
    """
    root = deps.checkpoint_root
    assert root is not None, "resume_run() needs a checkpoint_root"
    anchor = EpisodeCheckpoint.read(root, episode_id, step)
    assert anchor is not None, f"no checkpoint for episode={episode_id!r} step={step}"
    state = RunState.model_validate(anchor.run_state_dump)
    assert state.run_id == run_id

    # DataCenter 单点重建：事件主前缀 + goals 槽对齐。
    data_center = deps.data_center
    assert data_center is not None, "resume_run() needs a data_center (装配时注入)"
    data_center.rebuild(
        deps.trace.read_disk_events(FromHarnessToTraceToolReadDiskEventsReq()).events,
        state.goals,
    )
    state = state.model_copy(
        update={"resume_episode": ResumeEpisode(episode_id=episode_id, step=step)}
    )
    deps.run_id = run_id
    try:
        final = _invoke(deps, graph, state)
    except Exception as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RUN_ERROR,
                episode_id=run_id,
                step=0,
                error=exc_snapshot(exc),
            )
        )
        raise

    # run 级恢复标记**必须在 graph.invoke() 之后才 append**——这一局的
    # `episode.resume()` 内部会用同一个 cursor 调 `void_after()`，把磁盘上
    # 所有 `event_id > cursor` 的行（不分文件）都归档；这个标记事件本身
    # 的 id 必然 > cursor（它是 rebuild() 之后新分配的），如果在
    # `graph.invoke()` **之前**就写盘，会被这一局自己的 `void_after` 当场
    # 连带归档掉，在连续性判定里凭空留下一个洞（0909 实测踩到：
    # `restore_step` 的游标是 53，先写的这条标记恰好落在 id 54，
    # 结果自己被自己的 void_after 判定"> 53"而归档）。放到 `invoke()`
    # 之后写，此时该局的 void_after 已经跑完，不会再回头吃掉新事件。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHECKPOINT_RESTORE,
            step=0,
            episode_id=run_id,
            restored_episode_id=episode_id,
            restored_step=step,
            cursor=anchor.last_event_id,
        )
    )
    return close(deps, final, run_id)


def close(
    deps: HarnessDeps, final: dict[str, Any], run_id: str
) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
    """收尾：组装结算并写 RUN_END（`new_run` / `resume_run` 共用）。

    结算对象只活在这个函数里：写进 RUN_END 事件，然后拆成四个裸值交出去。
    """
    final_state = RunState.model_validate(final)
    outcomes = final_state.outcomes
    succeeded = sum(1 for o in outcomes if o.success)
    result = RunResp(
        run_id=run_id,
        outcomes=outcomes,
        total=len(outcomes),
        succeeded=succeeded,
        success_rate=(succeeded / len(outcomes)) if outcomes else 0.0,
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RUN_END,
            step=0,
            episode_id=run_id,
            outcome_run=result,
        )
    )
    return result.outcomes, result.total, result.succeeded, result.success_rate


def _invoke(deps: HarnessDeps, graph: CompiledStateGraph, state: RunState) -> dict[str, Any]:
    """进图：递 `RUN_RECURSION_LIMIT`（闸门）与 `deps`（唯一的 context）。

    **`context=deps` 是必需项**（D3/F10）：run 图的节点也是自由函数，依赖只从
    `runtime.context` 来；不给会让 `plan`/`dispatch`/`review` 读到一份空的 context
    ——炸在第一个读依赖的节点上。
    """
    return graph.invoke(
        state,
        {"recursion_limit": RUN_RECURSION_LIMIT},
        context=deps,
    )


__all__ = [
    "RUN_RECURSION_LIMIT",
    "close",
    "exc_snapshot",
    "new_run",
    "resume_run",
]
