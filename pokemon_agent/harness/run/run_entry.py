"""run 图的**图外侧门**：一个 run 的开局（`new_run`）。

和图内节点的分工，跟 `episode/episode_entry.py` 与它那些节点的分工是同一个意思：
**凡是"在进图之前必须先做完、且做完才有一个完整初值"的事，都住图外**。run 侧这件是

- `new_run`：写 `RUN_START` → 造初始 `RunState` → 进图 → 取结算（异常路径补 `RUN_ERROR`）。

异常时补一条 `RUN_ERROR` 再原样抛，**不吞**（跟 `episode_entry` 对 `EPISODE_ERROR`
的处理是同一个模式）。

**存档/恢复已整体删除**（见 `CHANGELOG.md` 2026-09-13 第 57 条）：原先这里有第二个
入口 `resume_run`（读存档锚点 → 重建 `RunState` → 进图 → 补 `CHECKPOINT_RESTORE`
→ 取结算），随 `EpisodeCheckpoint` 一起删掉了。

**`recursion_limit` 的常量住顶层 config**（`RUN_RECURSION_LIMIT`）：`_invoke()` 是它唯一
的读者，它是 run 级的**闸门**而不是预算——贴身的限在内层
`episode_entry.episode_budget()`（按剩余步数逐局算），两层的分工与来龙去脉见那个常量
自己的 docstring。

**函数名与 `episode_entry` 刻意不同**：那边是 `run_new`（"run 起一局"），
这里是 `new_run`（"起一个 run"）。两个模块各有各的 `run` 语义，同名会
让 `grep run_new` 撞出两处、而它们在不同的层级上——命名规则见
`PLAN_graph_composition.md` §5.3-5（`basename` 要能单独说清身份）的同一条判据。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.brain import Task
from pokemon_agent.config import RUN_RECURSION_LIMIT
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendReq,
    FromRunHarnessToEpisodeHarnessRunResp,
    RunResp,
    TraceKind,
)

from ..deps import HarnessDeps
from .run_state import RunState


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


def close(
    deps: HarnessDeps, final: dict[str, Any], run_id: str
) -> tuple[list[FromRunHarnessToEpisodeHarnessRunResp], int, int, float]:
    """收尾：组装结算并写 RUN_END（`new_run` 用）。

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
]
