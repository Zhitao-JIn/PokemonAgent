"""`judge`：这一局该不该停，在这一格一次性判完。

**图上唯一的终止判定节点**，只改 `done`/`success` 两处（紧密绑在一起的一小组，
同 `stall_key`/`stall_count`）——`observation` 本身不被这一格改动。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Goal
from pokemon_agent.config import JUDGE_HISTORY_STEPS, STALL_LIMIT
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToMemoryToolQueryRecentStepsReq,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import StepMemory

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
    # history/prompt，也不留 MODEL_CALL 账单（没问模型就没有账要记）。
    if obs.step == 0:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.JUDGE_VERDICT,
                meta={"source": "judge", "episode_id": state.episode_id, "step": obs.step},
                done=done,
                success=success,
                stalled=stalled,
                why="第 0 步不问模型",
            )
        )
        return {"done": done, "success": success}

    # 步骤 2：取最近 `JUDGE_HISTORY_STEPS` 条 step memory 当证据。**按条取**，
    # 不按决策分组——判定器要看的是"最近发生了什么"，事件逐个键发生，窗口就该按
    # 事件条数说（2026-09-14 定案，原先按决策取会让窗口随链长浮动，见 config 注释）。
    # prompt **不在这里拼**（0913 定案）：本节点只装素材，`BrainTool.judge()` 入口拼
    # （`prompts.judge_success.build_prompt()`）。
    history = deps.memory.query_recent_steps(
        FromHarnessToMemoryToolQueryRecentStepsReq(
            episode_id=state.episode_id, limit=JUDGE_HISTORY_STEPS
        )
    ).steps

    # 步骤 2.5 已并入 tool 层（0915 130）：本节点只装 history 素材，要带的
    # 截图由 `BrainTool.judge()` 对同一批 history 跑 `dedup_snapshots()` 取。

    # 步骤 3：问一次判定。**失败要在逃出去之前留痕**（0913 定案）——判定耗尽
    # 原样上抛，最终由 episode 边界补 `EPISODE_ERROR`，但那条只有边界
    # （step 写死 0、一个 message 串），看不出"是第几步的判定节点完了"。
    # 那段逻辑（落整条账 + 补 `CALL_EXHAUSTED`（`link="judge"`）+ 上抛）在
    # `_ask_judge` 里，第一次与后面的插话重问共用同一条路。`human_note=""` = 没被插话。
    verdict = _ask_judge(deps, goals[-1], history, state.episode_id, obs.step, "")

    # 步骤 4：判成才改——覆盖停摆/超时的结论，最后一帧仍可能真的达成。
    if verdict.done:
        done, success = True, True

    # 步骤 4.5：**插话**（0914 控制台改造）——把这次裁决亮给人。
    #
    # `judge` 的产物是"这一局该不该停"这**一个结论**（不是多字段结构体），
    # 但人的反馈在这里仍然走 `inject`（一句话）而不是 `audit`（认/推翻）：
    # `audit` 是**run 级**的概念（那一局算成算败、盖章进目标表），而这里是
    # **局内**的一步判断——它不盖章，只是本条链要不要换个方式。
    #
    # 人说了话就**带着它重问一次**（不设上限，与 `think_action` 同一契约）。
    # 重问的账照记：每次 `deps.brain_tool.judge()` 一笔 `JUDGE_CALL`。
    note = deps.reviewer.inject(
        FromHarnessToReviewerInjectReq(
            prompt=f"请审这次判定（第 {obs.step} 步：{'判成' if success else '判未成'}）",
            form=verdict,
            form_kind="JudgeVerdict",
        )
    )
    while note:
        verdict = _ask_judge(deps, goals[-1], history, state.episode_id, obs.step, note)
        if verdict.done:
            done, success = True, True
        note = deps.reviewer.inject(
            FromHarnessToReviewerInjectReq(
                prompt=f"再审这次判定（第 {obs.step} 步：{'判成' if success else '判未成'}）",
                form=verdict,
                form_kind="JudgeVerdict",
            )
        )

    # 步骤 5：判定结论留一条轻量事件（`EventType.JUDGE`）——账单（MODEL_CALL）归
    # model_call 列后，观测台上 judge 节点的内容靠这条。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_VERDICT,
            meta={"source": "judge", "episode_id": state.episode_id, "step": obs.step},
            done=done,
            success=success,
            stalled=stalled,
            why=verdict.why,
            input=verdict.calls[-1].payload.get("prompt", ""),
            output=verdict.calls[-1].payload.get("raw", ""),
        )
    )
    return {"done": done, "success": success}


def _ask_judge(
    deps: HarnessDeps,
    goal: Goal,
    history: list[StepMemory],
    episode_id: str,
    step: int,
    human_note: str,
) -> FromHarnessToBrainToolJudgeResp:
    """问一次判定、落一次账。**插话重问走这条路**（`human_note` 非空）。

    与第一次问的唯一区别是那个 `human_note` —— 它由 prompt 层拼在**最末尾**，
    压过上面所有规则。失败路径与第一次完全一致（落账 + `CALL_EXHAUSTED` + 上抛）。
    """
    verdict_req = FromHarnessToBrainToolJudgeReq(goal=goal, history=history, human_note=human_note)
    try:
        verdict = deps.brain_tool.judge(verdict_req)
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                meta={"source": "judge", "episode_id": episode_id, "step": step},
                kind=TraceKind.JUDGE_CALL,
                calls=list(exc.calls),
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CALL_EXHAUSTED,
                meta={"source": "judge", "episode_id": episode_id, "step": step},
                link="judge",
            )
        )
        raise
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_CALL,
            meta={"source": "judge", "episode_id": episode_id, "step": step},
            calls=verdict.calls,
            why=verdict.why,
        )
    )
    return verdict
