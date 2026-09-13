"""`judge`：这一局该不该停，在这一格一次性判完。

**图上唯一的终止判定节点**，只改 `done`/`success` 两处（紧密绑在一起的一小组，
同 `stall_key`/`stall_count`）——`observation` 本身不被这一格改动。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.config import JUDGE_DECISION_HISTORY, JUDGE_HISTORY_KEY_CAP, STALL_LIMIT
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToMemoryToolQueryRecentStepsReq,
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import dedup_snapshots, last_decisions
from pokemon_agent.trace import Source

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def judge(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """四类终止来源都在这合并，不分给别的节点。

    - 世界自己置 `done`（读 `obs.done`，世界层自己的信号，只读不改）；
    - 步数用尽；
    - 连续 `STALL_LIMIT` 步动作与画面机械状态都没变化（L2 护栏——`stall_count` 由
      上一轮 `detect_stall` 算出，这里只读不改）；
    - **目标达成没有**——这一类要问大脑。

    不管前三类是否已经成立，都照常问一次模型——**最后一帧仍然可能真的达成了目标**，
    这种情况要按成功记，不是按停摆/超时记，问的这次账（JUDGE）不能因为已经知道要
    终止就省略。本 episode 只解决栈顶（`goals[-1]`）；判成直接把 `done`/`success`
    打上，不弹栈——弹栈/压栈是 run 级 `reflect` 的职责。

    **例外：第 0 步不问模型**。失败重试是"栈顶保留、世界不重置、直接开新 episode
    重派"（见 `run/reflect`），重试 episode 第 0 步的这一帧和上一个失败 episode 最后
    一步已经判过的那一帧相同——再问一次模型是纯重复。**已知风险（用户已接受）**：
    这个判断对"全新目标第一次派发"的 episode 不成立——它的第 0 步从没被判过，理论上
    可能第一步就巧合达成，这里会漏判一次，要等第 1 步才会被发现（不会永久漏判，只是
    晚一步）。`entry.run_new()` 目前收不到"这是第几次派发"的信息，没法只在真正的重试
    时才跳过，所以是全局跳过。

    **契约：模型调不通/输不出合法裁决时抛 `MaxRetriesExceeded`**——`BrainTool.judge`
    重试 `BRAIN_MAX_ATTEMPTS` 次仍失败就上抛，本节点**不接**，由图的调用方决定
    这一局怎么收场。旧契约的"永不抛异常、失败返回 `done=False`"已废弃：那会让
    "判定器坏了"与"真的没达成"在数据里分不开——trace 里表现为成功率悄悄变 0，
    而"判定失效"这件事看不见。

    渲染 prompt 本身可能抛的 `KeyError`（模板占位符对不上）同样不吞：那是编程错误，
    不是模型不配合。

    前置条件：`state.observation` 非空、`episode_goals` 非空。
    后置条件：返回 `{"done": …, "success": …}`（**只这两处**）；重试耗尽时抛异常。
    """
    deps = runtime.context
    assert state.observation is not None, "judge before record_observation"
    obs = state.observation
    goals = state.episode_goals
    assert goals, "the goal stack must never be empty"

    # 步骤 1：三类不用问模型的终止——世界结束/步数用尽/停摆。
    stalled = state.stall_count >= STALL_LIMIT
    if stalled or obs.done or state.step >= state.task.max_steps:
        done, success = True, False
    else:
        done, success = False, False

    # 步骤 1.5：第 0 步不问模型（原因见上面的节点文档），非模型结论（stall/世界
    # 结束/步数用尽——第 0 步这三样必然都是 False）直接就是最终结论，不用拼
    # history/images/prompt，也不留 MODEL_CALL 账单（没问模型就没有账要记）。
    depth = len(goals) - 1
    if obs.step == 0:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.JUDGE_VERDICT,
                episode_id=state.episode_id,
                step=obs.step,
                done=done,
                success=success,
                stalled=stalled,
                depth=depth,
                why="第 0 步不问模型",
            )
        )
        return {"done": done, "success": success}

    # 步骤 2：取最近几条**链**当证据（换算见本文件的两个常量）。prompt **不在这里拼**
    # （0913 定案）：本节点只装素材，`BrainTool.judge()` 入口拼
    # （`prompts.judge_success.build_prompt()`）。
    # 检索面只认步号（`limit` 是"几条记忆"），所以要分两步取窗：先按键数上限取回
    # 尾部，再按决策裁到最近 `JUDGE_DECISION_HISTORY` 次。`last_decisions` 不把一次
    # 决策砍成半截——半截里"这一键之后为什么停"读不出来。
    recent = deps.memory.query_recent_steps(
        FromHarnessToMemoryToolQueryRecentStepsReq(
            episode_id=state.episode_id, limit=JUDGE_HISTORY_KEY_CAP
        )
    ).steps
    history = last_decisions(recent, JUDGE_DECISION_HISTORY)

    # 步骤 2.5：这次问模型要带的截图，去重后一并拿到（不再单独取 `snapshots`
    # ——"当前观测"改由 `judge_success.build_prompt()` 直接复用 `history`
    # 最后一条的"之后变成"，见 0909 CHANGELOG 条目）。
    images, _ = dedup_snapshots(list(history))

    verdict_req = FromHarnessToBrainToolJudgeReq(
        goal=goals[-1],
        history=history,
        images=images,
    )
    # 步骤 2.9：判定节点失败要**在逃出去之前留痕**（0913 定案）——判定耗尽
    # 原样上抛，最终由 episode 边界补 `EPISODE_ERROR`，但那条只有边界
    # （step 写死 0、一个 message 串），看不出"是第几步的判定节点完了"。
    # 这里先落整条账（`MODEL_CALL`），再补一条只说明"节点完了、为什么"的
    # `JUDGE_FAILED`，然后原样上抛。
    try:
        verdict = deps.brain_tool.judge(verdict_req)
    except MaxRetriesExceeded as exc:
        deps.trace.append_model_calls(
            FromHarnessToTraceToolAppendModelCallsReq(
                episode_id=state.episode_id,
                step=obs.step,
                source=Source.JUDGE,
                log=[(i, call) for i, call in enumerate(exc.calls, start=1)],
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.JUDGE_FAILED,
                episode_id=state.episode_id,
                step=obs.step,
                why=exc.last_reason,
            )
        )
        raise

    # 步骤 3：判定账单（MODEL_CALL，JUDGE）——账单与失败补 ERROR 由 tool 处理。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_CALL,
            episode_id=state.episode_id,
            step=obs.step,
            depth=depth,
            calls=verdict.calls,
            why=verdict.why,
        )
    )

    # 步骤 4：判成才改——覆盖停摆/超时的结论，最后一帧仍可能真的达成。
    if verdict.done:
        done, success = True, True

    # 步骤 5：判定结论留一条轻量事件（`EventType.JUDGE`）——账单（MODEL_CALL）归
    # model_call 列后，观测台上 judge 节点的内容靠这条。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_VERDICT,
            episode_id=state.episode_id,
            step=obs.step,
            done=done,
            success=success,
            stalled=stalled,
            depth=depth,
            why=verdict.why,
        )
    )
    return {"done": done, "success": success}
