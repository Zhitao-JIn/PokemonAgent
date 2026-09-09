"""把 req 里的领域对象渲染成 trace 事件的 payload——**纯函数，不碰 trace**。

从原 `trace/utils.py` 迁入（原文件按"utils 只被自己的模块使用"退役）。
每个渲染函数对应一种 `TraceKind`，收 `FromHarnessToTraceToolAppendReq`，
吐出 `(EventType, Source, payload)`——`append()` 的后三个位置参数；
`(episode_id, step)` 来自 req 公共字段，由 `TraceTool.append()` 统一拼装。
会连带产生 ERROR 事件的几个（`model_call`/`judge_call`/`verify_call`）
吐出这种三元组的 list，由 `TraceTool.append()` 展开逐条落盘。

**payload 字段格式是跨模块契约**：`evaluation/eval_report.py` 按字段名解析
（`cached_tokens`/`verdicts`/`attempt`/`success`……），harness 改字段名/删
字段会让报表**静默**算错——本文件的字段变更是 harness 与 evaluation 之间
的跨模块变更，改字段必须同步 evaluation 的解析逻辑。

各 kind 必填的 req 字段用每个函数入口的 assert 表达（precondition），
与 `FromHarnessToTraceToolAppendReq` 的 docstring 一一对应。
"""

from __future__ import annotations

import json

from pokemon_agent.schemas.communication import (
    FromHarnessToTraceToolAppendReq,
    RunOutcomeResp,
    StepVerifyVerdict,
)
from pokemon_agent.schemas.datastore import (
    EpisodeMemory,
    EventType,
    ObjectDialogEvent,
    ObjectFactEvent,
    ObjectWarpEvent,
    Source,
    StepMemory,
)
from pokemon_agent.schemas.domain import (
    ActionFromBrain,
    GoalForBrain,
    ModelCall,
    ObservationFromWorld,
    TaskForHarness,
)

RenderedEvent = tuple[EventType, Source, dict[str, str]]
"""`append(episode_id, step, type, source, payload)` 的后三个位置参数。"""


def _tag_attempt(payload: dict[str, str], attempt: int) -> dict[str, str]:
    """给 payload 盖上第几次尝试的号——重试记账，原 `harness/tag_attempt.py`
    的职责随 req 化收进 tool（harness 传 `attempt`，盖章在这里做）。
    """
    return {**payload, "attempt": str(attempt)}


# ---- run 边界（RunHarness，一个 run 可能跑好几个 episode）----


def run_start(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """**run 的边界必须进事件流**，跟 `episode_start` 是同一个理由：没有它，
    replay/统计分不出一个 run 从哪开始，也看不出初始目标栈的目标文字和判据
    长什么样（`success_criteria` 只有当时的判据原文，判定逻辑不在这里）。

    `episode_id` 位置放 `run_id`、`step` 恒为 0——run 级事件不挂在任何一局
    上，跟 `RunHarness.plan` 的 `MODEL_CALL`（`Source.PLAN`）是同一个约定。

    前置条件：req.task 列表非空语义由调用方保证（goals 可以为空列表）。
    """
    goals: list[TaskForHarness] = req.run_goals or []
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {
            "kind": "run_start",
            "goal_count": str(len(goals)),
            "goals": " > ".join(g.goal for g in goals),
            "success_criteria": " > ".join(g.success_criteria for g in goals),
        },
    )


def run_end(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """**run 的收尾必须进事件流。** 不记的话，光看 trace 分不出这个 run 是
    正常跑完（目标栈清空 / 人工喊停）还是半路死掉（撞
    `GraphRecursionError`、进程被杀……）——见 `docs/ROADMAP.md`
    "trace 生命周期不闭合"那条。异常路径走 `run_error`，不是这个函数。

    前置条件：req.outcome_run 非 None。
    """
    outcome: RunOutcomeResp = req.outcome_run
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {
            "kind": "run_end",
            "total": str(outcome.total),
            "succeeded": str(outcome.succeeded),
            "success_rate": f"{outcome.success_rate:.4f}",
        },
    )


def run_error(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """异常逃出 `RunHarness.run()` 之前把 `RUN_END` 补上——跟 `episode_error`
    是同一个理由：不补的话这个 run 在事件流里永远"没有结束"，离线统计时
    既不在成功里也不在失败里，直接从分母上消失。

    前置条件：req.error 非 None（异常的字符串快照）。
    """
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {
            "kind": "run_end",
            "total": "0",
            "succeeded": "0",
            "success_rate": "0.0",
            "why": req.error,
        },
    )


# ---- episode 边界 ----


def episode_start(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """**episode 的边界必须进事件流。** 没有它，光看日志分不出一次尝试从哪开始。

    任务本体快照进 payload（`goal`/`max_steps`）；**`task_id` 不进**——那是
    实验层的分组键，实验层自己知道在跑哪个任务。

    **`memory_carried` 必须显式传入，不给默认值**——开局时"这一局能检索到
    多少条跨局摘要经验"是调用方已经知道的事实，不是这一层该替它猜的。这个
    数字是 `evaluation/SPEC.md` 里"success rate 会不会被同批次内的记忆积累
    污染"这个问题的唯一诊断入口。

    前置条件：req.task、req.memory_carried 非 None。
    """
    task: TaskForHarness = req.task
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {
            "kind": "episode_start",
            "goal": task.goal,
            "max_steps": str(task.max_steps),
            "memory_carried": str(req.memory_carried),
        },
    )


def episode_end(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """**成功与否必须落进事件流。** 不记的话，光看日志算不出成功率——
    而那是这个项目唯一的一组硬数字。

    **判定依据不进这里**——它随最后一次判定的账单留档（`judge_call` 的
    `why`），不重复存。

    前置条件：req.outcome_episode 非 None。
    """
    outcome = req.outcome_episode
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {
            "kind": "episode_end",
            "success": str(outcome.success),
            "steps": str(outcome.steps),
            "reason": outcome.reason,
        },
    )


def episode_error(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """**异常逃出去之前必须把 EPISODE_END 补上。** 不补的话这一局在事件流里
    永远"没有结束"：离线统计成功率时它既不在成功里也不在失败里，
    **直接从分母上消失**——而 `MaxRetriesExceeded` 恰恰是最该被记成失败的那类。

    前置条件：req.error 非 None。
    """
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {
            "kind": "episode_end",
            "success": "False",
            "steps": "-1",
            "reason": "error",
            "why": req.error,
        },
    )


# ---- 账：每一次模型调用共用同一条翻译规则 ----


def model_call(req: FromHarnessToTraceToolAppendReq) -> list[RenderedEvent]:
    """一次模型调用 → 一条 `MODEL_CALL`，失败的再补一条 `ERROR`。

    **账单和失败模式是两件事**：前者回答"花了多少钱"，后者回答"为什么没
    拿到东西"。混进一条里，按失败类型聚合的时候就得去解析 payload 里的
    字符串。

    `req.attempt` 非 None 时给 payload 盖尝试号（重试记账，原 `tag_attempt`
    的职责收进 tool）。

    前置条件：req.source、req.call 非 None。
    """
    call: ModelCall = req.call
    payload = dict(call.payload)
    if req.attempt is not None:
        payload = _tag_attempt(payload, req.attempt)
    events = [(EventType.MODEL_CALL, req.source, payload)]
    if call.error_kind:
        events.append(
            (
                EventType.ERROR,
                req.source,
                {
                    "kind": call.error_kind,
                    "reason": call.error,
                    "attempt": payload.get("attempt", ""),
                },
            )
        )
    return events


def judge_call(req: FromHarnessToTraceToolAppendReq) -> list[RenderedEvent]:
    """判定的账单，多记一个 `depth`——子目标判得多不代表任务判得多，
    两种粒度必须分得开，否则"判定花了多少钱"这个数会被子目标的量淹掉。

    **判定依据（`why`）在这里留档**：成功率是要报的数字，每一个 True
    都得说得出依据。依据跟着账单走，EPISODE_END 不再重复存。

    前置条件：req.call、req.depth、req.why 非 None。
    """
    events = model_call(req)
    return [
        (event_type, Source.JUDGE, {**payload, "depth": str(req.depth), "why": req.why})
        for event_type, _source, payload in events
    ]


def verify_call(req: FromHarnessToTraceToolAppendReq) -> list[RenderedEvent]:
    """校验器（`Brain.verify_and_summarize`）的账单，多记一份结构化
    `verdicts`——每条 step 记忆判没判、为什么，结构化落 trace 免去对
    `raw` 文本的反解析（背景见 `CHANGELOG.md` 2026-09-02 条目）。

    前置条件：req.call、req.verdicts 非 None。
    """
    verdicts: list[StepVerifyVerdict] = req.verdicts
    rendered = json.dumps([v.model_dump() for v in verdicts], ensure_ascii=False)
    events = model_call(req)
    return [
        (event_type, Source.VERIFY, {**payload, "verdicts": rendered})
        for event_type, _source, payload in events
    ]


def decision_failed(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """重试用尽时的那条错误事件。

    前置条件：req.call 非 None（最后一次失败的账）。
    """
    last: ModelCall = req.call
    return (
        EventType.ERROR,
        Source.DECISION,
        {
            "kind": "MaxRetriesExceeded",
            "reason": "max_retries_exceeded",
            "last": f"{last.error_kind}: {last.error}",
        },
    )


def permission_skipped(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """记录一次权限拒绝后的可观测降级。

    `req.source` 应按"被拒的到底是哪个子系统"传（记忆子系统的读/写/蒸馏
    权限被拒传 `Source.MEMORY`），不传是历史行为（HARNESS）。

    前置条件：req.permission、req.function、req.fallback 非 None。
    """
    source = req.source or Source.HARNESS
    return (
        EventType.ERROR,
        source,
        {
            "kind": "PermissionSkipped",
            "permission": req.permission,
            "function": req.function,
            "fallback": req.fallback,
        },
    )


# ---- 一步之内的各类事件 ----


def observe(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """**facts 必须进 payload。** 它才是观测的实质内容。只记 summary 的话，
    replay 出来只剩「你在野外」这种废话。

    **`goals` 也要跟着这一帧一起记**——读日志的人拿得到"这一帧、这个决策，
    当时的目标栈长什么样"（run 级投影，判只判栈顶）。

    这一帧感知时实际截下来的原始画面**不走 payload**：调用方把它放
    `req.frame_png`，`TraceTool.append()` 转交给 `TraceEvent.frame_png`
    （bytes 字段，不是路径）——渲染只管纯文本 payload。

    前置条件：req.obs 非 None。
    """
    obs: ObservationFromWorld = req.obs
    goals: list[GoalForBrain] = req.goals or []
    return (
        EventType.VIEW,
        Source.PERCEPTION,
        {
            "kind": "frame",
            "status": obs.status,
            "scene": obs.facts.get("scene", ""),
            "overlay": obs.facts.get("overlay", ""),
            "facts": json.dumps(obs.facts, ensure_ascii=False),
            "goals": _render_goal_stack(goals),
        },
    )


def memory_read(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """这一步从记忆里读出来的**全部**东西：单步情景记忆（检索到的几条）+
    语义记忆（`known_objects`：这张地图上互动过的东西；`knowledge`：和坐标
    无关的通用先验）+ 跨局摘要记忆（`episode_memories`：和当前任务相关的、
    别的局蒸馏出的经验）。

    四种读现在分散在四个 `retrieve_*` 节点里查，但事件仍然**共用一条**——
    在 `enrich_observation` 那格合并着写，拆成多条事件反而会让人以为它们
    发生在循环的不同位置。`known_objects`/`knowledge`/`episode_memories`
    只在非空时才进 payload：大多数步的知识库内容不会变，留一条空字符串
    没有信息量；场景过滤命中为空也是正常情况，不是错误。

    前置条件：req.memories 非 None（可以为空列表——检索命中零条是常态）。
    """
    memories: list[StepMemory] = req.memories
    episode_memories: list[EpisodeMemory] = req.episode_memories or []
    knowledge_sources: list[str] = req.knowledge_sources or []
    payload = {
        "kind": req.read_kind or "read_merge",
        "count": str(len(memories)),
        "step_memory_count": str(len(memories)),
        "refs": " ".join(f"({m.episode_id}, {m.step})" for m in memories),
    }
    if req.known_objects:
        payload["known_objects"] = "1"
        payload["known_object"] = "1"
        # **全文进 payload**——这段是决策模型真正读到的东西，日志里存不全，
        # 事后就无法回答"它当时到底看到了什么"（截断史的教训见 `CHANGELOG.md`
        # 2026-09-03 条目）。
        payload["known_objects_text"] = req.known_objects
        payload["known_object_count"] = str(len(req.known_objects.split("\n\n")))
        payload["known_objects_chars"] = str(len(req.known_objects))
    if req.knowledge:
        payload["knowledge"] = "1"
        payload["knowledge_sources"] = " ".join(knowledge_sources)
    if episode_memories:
        payload["episode_memory_count"] = str(len(episode_memories))
        payload["episode_level_count"] = str(len(episode_memories))
        payload["episode_memory_refs"] = " ".join(m.episode_id for m in episode_memories)
    return (EventType.MEMORY_IO, Source.MEMORY, payload)


def action_chain(action: ActionFromBrain) -> dict[str, str]:
    """动作链在 payload 里的形状。**`think` 和 `act` 共用这一个函数**——
    记的是同一条链，形状不一致的话"想按的"和"按下去的"就没法直接比对。

    **结构化的 `sequence` 必须记，不能只记 `action` 那行渲染文本。**
    渲染文本（`up×4 -> down×2`）是给人读的；"链平均多长、多少步用到了链"
    这类聚合如果去解析它，就得反向分词，而分词一旦和 `describe()` 的措辞
    漂移，统计会**静默地**错。

    **payload 里没有顶层 `name` / `args`**：格式只有 `sequence` 一种；
    恒为空的 `args` 会让读日志的人误读成"模型这次没给参数"。
    """
    segments = action.segments()
    return {
        "action": action.describe(),
        "sequence": json.dumps([segment.model_dump() for segment in segments], ensure_ascii=False),
        "segment_count": str(len(segments)),
        "press_count": str(sum(segment.times for segment in segments)),
    }


def human_note_injected(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """人类实时插话被这一步 `think_action` 消费了一条（`RunDataCenter`
    的 human_note 槽）。**只在真的取到非空文本时才记**——没人插话是常态，
    不该每步都留一条空事件。

    挂 `LIFECYCLE`（跟 `episode_start`/`step` 同类：流程外部注入的一个节点，
    不是模型产物，不适合 `LLM_OUTCOME`）；`source=HARNESS`——是 harness 把
    外部输入接进这一步的循环，不是某条模型链自己产生的。

    前置条件：req.text 非空。
    """
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {"kind": "human_note", "text": req.text},
    )


def think(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """把这一步选出的动作拼成事件（`LLM_OUTCOME`，kind=intent）。

    前置条件：req.action、req.attempt 非 None。
    """
    action: ActionFromBrain = req.action
    return (
        EventType.LLM_OUTCOME,
        Source.DECISION,
        {
            "kind": "intent",
            **action_chain(action),
            "thought": action.thought,
            # rationale 也记在这里，不只依赖 MEMORY_WRITE——
            # **无记忆基线组不写记忆**，那时 rationale 只剩这一处落点。
            "rationale": json.dumps(action.rationale, ensure_ascii=False),
            "attempt": str(req.attempt),
        },
    )


def act(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """把这一次按键拼成事件。

    **和 `think` 记的是同一条链**（同一个 `action_chain`），差别只在来源：
    `think` 是大脑打算按的，`act` 是世界真的按了的。两条形状一致，正是为了
    能直接比对——一旦哪天执行层又开始改写动作，diff 立刻看得见。

    **不记"结果"。** 按完之后世界变成什么样，答案是下一条 OBSERVE 事件里
    那份完整观测，不是一句转述。

    前置条件：req.action 非 None。
    """
    action: ActionFromBrain = req.action
    return (
        EventType.ACT,
        Source.WORLD,
        {"kind": "executed", **action_chain(action)},
    )


def memory_write(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """把新写入的那条单步情景记忆拼成事件。

    `(episode_id, step)` 就是这条记忆的坐标（一步一条），作为 `ref` 进 payload。

    前置条件：req.entry 非 None。
    """
    entry: StepMemory = req.entry
    return (
        EventType.MEMORY_IO,
        Source.MEMORY,
        {
            "kind": "write_step",
            "ref": f"({entry.episode_id}, {entry.step})",
            "content": entry.render(),
        },
    )


def stall_check(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """`detect_stall`（L2 护栏）每一步算出的停摆键/连续计数快照。

    这条把每一步停摆判定的构成过程记下来：哪一步开始连续不动、涨到第几次
    才触发，不用重放整局重新算一遍就能看见。**没有 token 花费**，
    `Source.HARNESS`——这是图控制的记账，不是模型调用。

    前置条件：req.stall_key、req.stall_count 非 None。
    """
    return (
        EventType.ACT,
        Source.HARNESS,
        {"kind": "stall", "stall_key": req.stall_key, "stall_count": str(req.stall_count)},
    )


def object_note(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """语义记忆和情景记忆是两回事，分开写——见 `memory_write`。

    把一条 object 交互事件拼成 trace 记录。**payload 记事件本身**
    （type/对象格/姿势/载荷）：事件就是存储的真源，trace 里这份副本让
    replay 不必回读事件库。

    前置条件：req.event 非 None。
    """
    event: ObjectFactEvent = req.event
    if isinstance(event, ObjectDialogEvent):
        content = f'对话"{event.text}"'
    elif isinstance(event, ObjectWarpEvent):
        content = f"进入新地图{event.map_id}"
    else:
        content = "无效果"
    actor = event.actor_place
    return (
        EventType.MEMORY_IO,
        Source.MEMORY,
        {
            "kind": "write_object",
            "type": event.type,
            "key": event.place.key,
            "landmark_kind": event.kind,
            "actor": f"x={actor.x} y={actor.y} 按 {event.button}",
            "content": content,
        },
    )


def episode_memory_write(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """跨局摘要记忆写入（蒸馏成功）拼成事件。`Source.MEMORY`——这条链的
    token 花费和决策链分开记账；**账本身在 `model_call`（`Source.MEMORY`）里**。

    **payload 记全（元数据 + 经验本体）**：这是 `EpisodeMemory` 的 trace
    格式副本——重启后能从 trace 重建经验，run 级读它也能拿到每局经验，
    不必查记忆库。

    前置条件：req.memory 非 None。
    """
    memory: EpisodeMemory = req.memory
    return (
        EventType.MEMORY_IO,
        Source.MEMORY,
        {
            "kind": "write_episode",
            "summary": memory.summary,
            "reusable_patterns": json.dumps(memory.reusable_patterns, ensure_ascii=False),
            "critical_decisions": json.dumps(memory.critical_decisions, ensure_ascii=False),
            "failure_points": json.dumps(memory.failure_points, ensure_ascii=False),
            "quality_score": str(memory.quality_score),
            "quality_rationale": memory.quality_rationale,
            "applicable_scenes": " ".join(memory.applicable_scenes),
            "tags": " ".join(memory.tags),
        },
    )


def episode_summary_error(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """蒸馏解析失败拼成事件。

    前置条件：req.reason 非空。
    """
    return (
        EventType.ERROR,
        Source.MEMORY,
        {"kind": "EpisodeSummaryParseFailure", "reason": req.reason},
    )


# ---- "节点活动"轻量事件：给链式观测台补全节点痕迹，都不经模型 ----
#
# 这批事件是零成本记账（无模型调用、payload 轻量），Source 各自归位：
# 掩码/步进/图控制挂 HARNESS，检索挂 MEMORY，判定挂 JUDGE，动作后观察挂
# PERCEPTION，校验挂 VERIFY。


def judge_verdict(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """judge 的判定结论（非账单）。

    **不重复存模型 raw**：MODEL_CALL 归列后链上 judge 的可见内容靠这条。
    `why` 与 MODEL_CALL payload 里的同源，这里记一份便于不翻账单就能看
    结论；`depth` 与账单里一致（子目标层级，详见 `judge_call`）。

    前置条件：req.done/success/stalled/depth/why 非 None。
    """
    return (
        EventType.LLM_OUTCOME,
        Source.JUDGE,
        {
            "kind": "verdict",
            "done": str(req.done).lower(),
            "success": str(req.success).lower(),
            "stalled": str(req.stalled).lower(),
            "depth": str(req.depth),
            "why": req.why,
        },
    )


def action_space(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """get_action_space 的输出：这一步允许的动作名（掩码结果）。

    `Source.HARNESS`——掩码是图控制做的零成本账，不是世界/模型的产出。

    前置条件：req.names 非 None。
    """
    names: list[str] = req.names
    return (
        EventType.ACT,
        Source.HARNESS,
        {"kind": "space", "count": str(len(names)), "names": " ".join(names)},
    )


def retrieve_node(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """一次检索的命中摘要（不带全文）。read_kind ∈
    step/global/knowledge/object/verify_step。

    **全文不重复**：主循环四路的检索内容只存在于 enrich_observation 合并出
    的那一条读（MEMORY_IO，kind=read_merge）；这里每节点一条 count+refs，
    用于链上定位"这一路读到了什么量级"。`Source.MEMORY`——检索不花模型的
    钱。信封 kind = read_<原 read_kind>（verify_step → read_verify_steps）。

    前置条件：req.read_kind、req.count、req.refs 非 None。
    """
    sub = {
        "step": "read_step",
        "global": "read_global",
        "knowledge": "read_knowledge",
        "object": "read_object",
        "verify_step": "read_verify_steps",
    }.get(req.read_kind, req.read_kind)
    return (
        EventType.MEMORY_IO,
        Source.MEMORY,
        {"kind": sub, "count": str(req.count), "refs": req.refs},
    )


def step_advance(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """advance_step 节点：步数推进的结果。`Source.HARNESS`——图控制的记账。

    前置条件：req.next_step 非 None。
    """
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {"kind": "step", "next_step": str(req.next_step)},
    )


def look_after(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """look_after_action 的观察摘要（非账单）。

    该节点的痕迹除感知 MODEL_CALL 外只有这条；完整 facts 紧跟其后由下一步
    look 的 OBSERVE 携带，这里只记轻量摘要。`Source.PERCEPTION`——它也是
    "看"的一种，只是不比账单。

    前置条件：req.scene/overlay/status/done 非 None。
    """
    return (
        EventType.VIEW,
        Source.PERCEPTION,
        {
            "kind": "after",
            "scene": req.scene,
            "overlay": req.overlay,
            "status": req.status,
            "done": str(req.done).lower(),
        },
    )


def verify_result(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """verify_steps 的校验结论摘要。

    逐条 verdicts 仍在 MODEL_CALL(VERIFY) 的 payload（报表按它解析失效率）；
    这里补轻量汇总当链上内容。`Source.VERIFY`——和判定一样独立记账。

    前置条件：req.checked、req.unreliable 非 None。
    """
    return (
        EventType.LLM_OUTCOME,
        Source.VERIFY,
        {"kind": "audit", "checked": str(req.checked), "unreliable": str(req.unreliable)},
    )


def plan_verdict(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """run 级 `plan` 节点的决策结论（非账单）。

    跟 `judge_verdict`/`verify_result` 是同一个模式：账单（MODEL_CALL）答
    "花了多少钱"，这条（LLM_OUTCOME）答"这一格给了什么结论"，两件事分开记
    （拆分背景见 `CHANGELOG.md` 2026-09-04 条目）。

    `episode_id` 位置放 `run_id`、`step` 恒为 0——跟 `Source.PLAN` 的
    `MODEL_CALL`、`run_start`/`run_end` 是同一个约定（run 级事件不挂在
    任何一局上）。`Source.PLAN`——不用 `HARNESS`，理由同 `MODEL_CALL` 那条：
    `plan` 是一次真实模型调用产出的结论，不是零成本记账。

    pushed：压入的新目标描述，按 `push_goals` 原始列表顺序（**调用方注意**：
    这是模型提出的优先级顺序——"先做"在前，不是最终真正入栈的顺序；
    实际入栈时调用方会把这份列表反过来 append，好让列表第一项落在栈顶、
    最先被派发，这里记的是模型决策本身，不是入栈后的物理顺序）。

    前置条件：req.done、req.pushed、req.why 非 None。
    """
    pushed: list[str] = req.pushed
    return (
        EventType.LLM_OUTCOME,
        Source.PLAN,
        {
            "kind": "verdict",
            "done": str(req.done).lower(),
            "pushed_count": str(len(pushed)),
            "pushed_goals": " | ".join(pushed),
            "why": req.why,
        },
    )


# ---- 纯格式化，不单独对外暴露，供 observe() 用 ----


def _render_goal_stack(goals: list[GoalForBrain]) -> str:
    """把目标栈压成一行，塞进 `observe` 的 payload。**栈顶（当前要做的）在最后。**

    跟 `Brain._render_goals`（多行、给模型读、栈顶在最上面）刻意不同：
    一个是给人在日志里扫一眼查重复，一个是给模型逐行读的完整 prompt 片段，
    两者的读者和用途都不一样，没必要共用一份格式。
    """
    return " > ".join(f"[{depth}]{g.goal}" for depth, g in enumerate(goals))


def checkpoint_restore(req: FromHarnessToTraceToolAppendReq) -> RenderedEvent:
    """恢复发生的接缝标记（PLAN_checkpoint §5 步骤 9）——replay/统计据此
    识别时间线在此处接续，此前同号的废弃数据已在 voided 归档。
    """
    return (
        EventType.LIFECYCLE,
        Source.HARNESS,
        {
            "kind": "checkpoint_restore",
            "restored_episode_id": req.restored_episode_id or "",
            "restored_step": str(req.restored_step if req.restored_step is not None else -1),
            "cursor": str(req.cursor if req.cursor is not None else -1),
        },
    )
