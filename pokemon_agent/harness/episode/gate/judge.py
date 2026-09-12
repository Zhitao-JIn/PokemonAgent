"""`judge`：这一局该不该停，在这一格一次性判完。

**图上唯一的终止判定节点**，只改 `done`/`success` 两处（紧密绑在一起的一小组，
同 `stall_key`/`stall_count`）——`observation` 本身不被这一格改动。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.prompts import judge_success as judge_success_prompt
from pokemon_agent.providers import ModelCall
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToMemoryToolQueryRecentStepsReq,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.schemas.memory import dedup_snapshots, last_decisions
from pokemon_agent.trace import TraceKind

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState
from ..press.detect_stall import STALL_LIMIT

JUDGE_DECISION_HISTORY = 2
"""判定器能看到本局最近几条**链**（`render(reason=False)`，不含决策者的主张）。

**单位是决策，不是步**：一次决策 = 一串键，所以"最近 2 次决策"就是换粒度之前的
"最近 2 步"（那时一步一步都是一次决策）。2026-09-11 粒度下沉到单键之后若还按步取，
判定器的时间视野会被**静默除以决策长度**（一次决策能按 8 键），而它判的"事件"类判据
前提就是"证据可能在前几次决策的快照里"——所以这里换的是**单位**，数字 2 没动
（详见 `docs/spec/harness/PLAN_action_step_granularity.md` §7.4）。

窗口大小的取舍（含已知风险）记录在 `CHANGELOG.md` 2026-09-05 条目。"""

JUDGE_HISTORY_KEY_CAP = 8
"""上面那个窗口一次**最多取几个键**（查询上限，也是渲染上限）。

**为什么要有帽**：链长没有上限（`MAX_SEGMENTS × MAX_TIMES` = 32 键），两条长链能把
判定器的 prompt 顶到十几条记忆。8 = 一条打满 `MAX_TIMES` 的单段链：实测一条记忆
渲成文本约 490 字符、判定 prompt 本体约 4 千字符，8 条就是它的量级上限。真机实测
（2026-09-11 四次 run）`press_count` 全是 1，这个帽现在根本碰不到——它防的是链一长
就静默膨胀。"""


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

    **契约：本节点永不抛异常**（`Brain.judge` 的既有约定）。渲染 prompt 本身可能抛
    `KeyError`（模板占位符对不上），在这里就近吞掉、转成一条 `done=False` 的判定。

    前置条件：`state.observation` 非空、`episode_goals` 非空。
    后置条件：返回 `{"done": …, "success": …}`（**只这两处**）。
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

    # 步骤 2：取最近几条**链**当证据（换算见本文件的两个常量），prompt 由
    # `pokemon_agent.prompts.judge_success` 拼、回填进同一个 req 再交给 Brain
    # （同 decide_action 的模式）——但本节点扛着"永远不抛异常"的契约，渲染搬出来
    # 之后这条契约不能丢：拼装本身可能抛的 KeyError（模板占位符对不上）在这里
    # 就近吞掉，不能让它一路冒穿 Harness。
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
    try:
        verdict_req = verdict_req.model_copy(
            update={"prompt": judge_success_prompt.build_prompt(verdict_req)}
        )
    except Exception as exc:  # noqa: BLE001  同 Brain.judge() 原有的取舍
        verdict = FromHarnessToBrainToolJudgeResp(
            done=False,
            why=f"判定调用失败：{type(exc).__name__}",
            call=ModelCall(
                payload={"ok": "False", "attempt": "1"},
                error_kind=type(exc).__name__,
                error=f"{exc}",
            ),
        )
    else:
        verdict = deps.brain_tool.judge(verdict_req)

    # 步骤 3：判定账单（MODEL_CALL，JUDGE）——账单与失败补 ERROR 由 tool 处理。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_CALL,
            episode_id=state.episode_id,
            step=obs.step,
            depth=depth,
            call=verdict.call,
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
