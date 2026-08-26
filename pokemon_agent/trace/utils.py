"""把领域对象组装成 `TracePort.append()` 能接收的结构——**纯函数，不碰 trace**。

每个函数收 `episode_id`/`step` 加上这一类事件需要的领域对象（`Observation`/
`Action`/`Goal`/`ModelCall`……），吐出一个五元组
`(episode_id, step, EventType, Source, payload)`，正好是 `append()` 的五个
位置参数——调用方直接 `trace.append(*trace_utils.xxx(...))`。会连带产生
`ERROR` 事件的几个（`model_call`/`judge_call`）吐出的是这种五元组的 `list`。

这一层**不认识 `TracePort`**，不导入它，也不做任何 I/O——纯粹是
"领域对象 → dict[str, str]"的转换，可以脱离 trace/Harness 单独单元测试
（给一个 `Observation` 断言吐出来的 payload 长什么样，不需要造一个假 `TracePort`）。
`append()` 这一步、以及"这一步该不该记"的判断，都留在 `Harness` 手里——
这一层只管"记的话该记成什么样"。
"""

from __future__ import annotations

import json

from pokemon_agent.schemas.action import Action, Goal
from pokemon_agent.schemas.episode_memory import EpisodeMemory
from pokemon_agent.schemas.step_memory import StepMemory
from pokemon_agent.schemas.object_fact import ObjectFact
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.schemas.task import Task
from pokemon_agent.schemas.trace import EpisodeOutcome, EventType, ModelCall, Source

AppendArgs = tuple[str, int, EventType, Source, dict[str, str]]
"""`append(episode_id, step, type, source, payload)` 的五个位置参数。"""


# ---- episode 边界 ----

def episode_start(episode_id: str, task: Task, memory_carried: int) -> AppendArgs:
    """**episode 的边界必须进事件流。** 没有它，光看日志分不出一次尝试从哪开始，
    更不知道它带了多少条记忆进来——而那正是 A/B 实验的自变量本身。

    拼出这一局的开始事件。
    """
    return (
        episode_id, 0, EventType.EPISODE_START, Source.HARNESS,
        {"task_id": task.task_id, "goal": task.goal,
         "max_steps": str(task.max_steps), "memory_carried": str(memory_carried)},
    )


def episode_end(episode_id: str, outcome: EpisodeOutcome, why: str) -> AppendArgs:
    """**成功与否必须落进事件流。** 不记的话，光看日志算不出成功率——
    而那是这个项目唯一的一组硬数字。

    拼出这一局的结束事件，带上成败与依据。
    """
    return (
        episode_id, outcome.steps, EventType.EPISODE_END, Source.HARNESS,
        {"success": str(outcome.success), "steps": str(outcome.steps),
         "reason": outcome.reason, "task_id": outcome.task_id,
         # 判定给的理由要留档：成功率是要报的数字，**每一个 True 都得说得出依据**
         "why": why},
    )


def episode_error(episode_id: str, task_id: str, exc: Exception) -> AppendArgs:
    """**异常逃出去之前必须把 EPISODE_END 补上。** 不补的话这一局在事件流里
    永远"没有结束"：离线统计成功率时它既不在成功里也不在失败里，
    **直接从分母上消失**——而 `MaxRetriesExceeded` 恰恰是最该被记成失败的那一类。

    把逃出来的异常拼成一条结束事件。
    """
    return (
        episode_id, 0, EventType.EPISODE_END, Source.HARNESS,
        {"success": "False", "steps": "-1", "reason": "error", "task_id": task_id,
         "why": f"{type(exc).__name__}: {exc}"[:300]},
    )


# ---- 账：每一次模型调用共用同一条翻译规则 ----

def model_call(episode_id: str, step: int, source: Source, call: ModelCall) -> list[AppendArgs]:
    """一次模型调用 → 一条 `MODEL_CALL`，失败的再补一条 `ERROR`。

    **账单和失败模式是两件事**：前者回答"花了多少钱"，后者回答"为什么没拿到东西"。
    混进一条里，按失败类型聚合的时候就得去解析 payload 里的字符串。

    把一次模型调用拼成账单，失败的再补一条错误。
    """
    events = [(episode_id, step, EventType.MODEL_CALL, source, call.payload)]
    if call.error_kind:
        events.append((
            episode_id, step, EventType.ERROR, source,
            {"kind": call.error_kind, "reason": call.error,
             "attempt": call.payload.get("attempt", "")},
        ))
    return events


def judge_call(episode_id: str, step: int, depth: int, call: ModelCall) -> list[AppendArgs]:
    """判定的账单，多记一个 `depth`——子目标判得多不代表任务判得多，
    两种粒度必须分得开，否则"判定花了多少钱"这个数会被子目标的量淹掉。

    同上，但多带一个目标层号。
    """
    return model_call(
        episode_id, step, Source.JUDGE,
        call.model_copy(update={"payload": {**call.payload, "depth": str(depth)}}),
    )


def decision_failed(episode_id: str, step: int, last: ModelCall) -> AppendArgs:
    """重试用尽时的那条错误事件。"""
    return (
        episode_id, step, EventType.ERROR, Source.DECISION,
        {"kind": "MaxRetriesExceeded", "reason": "max_retries_exceeded",
         "last": f"{last.error_kind}: {last.error}"},
    )


def permission_skipped(
    episode_id: str,
    step: int,
    permission: str,
    function: str,
    fallback: str,
) -> AppendArgs:
    """记录一次权限拒绝后的可观测降级。"""
    return (
        episode_id, step, EventType.ERROR, Source.HARNESS,
        {"kind": "PermissionSkipped", "permission": permission,
         "function": function, "fallback": fallback},
    )


# ---- 一步之内的各类事件 ----

def observe(episode_id: str, obs: Observation, goals: list[Goal]) -> AppendArgs:
    """**facts 必须进 payload。** 它才是观测的实质内容。只记 summary 的话，
    replay 出来只剩「你在野外」这种废话。

    **`goals` 也要跟着这一帧一起记**——以前目标栈只在 `GOAL_PUSH`/`GOAL_POP`
    事件里出现过一次，读日志的人拿不到"这一帧、这个决策，当时的栈长什么样"。

    把这一帧观测拼成事件。
    """
    return (
        episode_id, obs.step, EventType.OBSERVE, Source.PERCEPTION,
        {"status": obs.status,
         "scene": obs.facts.get("scene", ""), "overlay": obs.facts.get("overlay", ""),
         "facts": json.dumps(obs.facts, ensure_ascii=False),
         "goals": _render_goal_stack(goals)},
    )


def memory_read(
    episode_id: str, step: int, memories: list[StepMemory],
    known_objects: str = "", knowledge: str = "",
    episode_memories: list[EpisodeMemory] = (),
    knowledge_sources: list[str] = (),
) -> AppendArgs:
    """这一步从记忆里读出来的**全部**东西：单步情景记忆（检索到的几条）+ 语义记忆
    （`known_objects`：这张地图上互动过的东西；`knowledge`：和坐标无关的通用先验）
    + 跨局摘要记忆（`episode_memories`：和当前任务相关的、别的局蒸馏出的经验）。

    四种读都发生在 `retrieve_memory` 这一个节点里，所以**共用一条事件**——
    拆成多条事件反而会让人以为它们发生在循环的不同位置。`known_objects`/
    `knowledge`/`episode_memories` 只在非空时才进 payload：大多数步的知识库内容
    不会变，但坐标为 None（比如刚重置、过场动画里）时 `known_objects` 确实是空的，
    留一条空字符串没有信息量；`episode_memories` 同理——场景过滤命中为空也是
    正常情况（还没积累过相关经验），不是错误。

    把这一步读到的四类记忆拼成一条事件。
    """
    payload = {
        "count": str(len(memories)),
        "step_memory_count": str(len(memories)),
        "refs": " ".join(f"({m.episode_id}, {m.step})" for m in memories),
    }
    if known_objects:
        payload["known_objects"] = "1"
        payload["known_object"] = "1"
        # **全文进 payload。** 以前这里只存每条的首行、截到 80 字符，
        # 于是控制台上看到的是半截档案（`…x=3 y=4→dow`），而且因为当时
        # `query_objects` 用单换行拼接，整段被当成一条，实际上只显示了第一条。
        # 这一段是决策模型真正读到的东西：日志里存不全，事后就无法回答
        # "它当时到底看到了什么"——而那是 replay 存在的全部理由。
        payload["known_objects_text"] = known_objects
        payload["known_object_count"] = str(len(known_objects.split("\n\n")))
        payload["known_objects_chars"] = str(len(known_objects))
    if knowledge:
        payload["knowledge"] = "1"
        payload["knowledge_sources"] = " ".join(knowledge_sources)
    if episode_memories:
        payload["episode_memory_count"] = str(len(episode_memories))
        payload["episode_level_count"] = str(len(episode_memories))
        payload["episode_memory_refs"] = " ".join(m.episode_id for m in episode_memories)
    return (episode_id, step, EventType.MEMORY_READ, Source.DECISION, payload)


def action_chain(action: Action) -> dict[str, str]:
    """动作链在 payload 里的形状。**`think` 和 `act` 共用这一个函数**——
    记的是同一条链，形状不一致的话"想按的"和"按下去的"就没法直接比对。

    **结构化的 `sequence` 必须记，不能只记 `action` 那行渲染文本。**
    渲染文本（`up×4 -> down×2`）是给人读的；"链平均多长、多少步用到了链"
    这类聚合如果去解析它，就得反向分词，而分词一旦和 `describe()` 的措辞漂移，
    统计会**静默地**错。

    **旧的顶层 `name` / `args` 不再进 payload。** 格式只剩 `sequence` 一种，
    留一个恒为空的 `args` 会让读日志的人以为"模型这次没给参数"——那正是
    这个字段当初存在的理由，理由没了字段就该走。

    把一条动作链拼成 payload 片段。
    """
    segments = action.segments()
    return {
        "action": action.describe(),
        "sequence": json.dumps(
            [segment.model_dump() for segment in segments], ensure_ascii=False
        ),
        "segment_count": str(len(segments)),
        "press_count": str(sum(segment.times for segment in segments)),
    }


def think(episode_id: str, step: int, action: Action, attempt: int) -> AppendArgs:
    """把这一步选出的动作拼成事件。"""
    return (
        episode_id, step, EventType.THINK, Source.DECISION,
        {**action_chain(action),
         "thought": action.thought,
         # rationale 也记在这里，不只依赖 MEMORY_WRITE——
         # **无记忆基线组不写记忆**，那时 rationale 只剩这一处落点。
         "rationale": json.dumps(action.rationale, ensure_ascii=False),
         "attempt": str(attempt)},
    )


def act(episode_id: str, step: int, action: Action) -> AppendArgs:
    """把这一次按键拼成事件。

    **和 `think` 记的是同一条链**（同一个 `action_chain`），差别只在来源：
    `think` 是大脑打算按的，`act` 是世界真的按了的。两条形状一致，正是为了
    能直接比对——一旦哪天执行层又开始改写动作，diff 立刻看得见。

    **不记"结果"。** 按完之后世界变成什么样，答案是下一条 OBSERVE 事件里那份
    完整观测，不是一句转述。
    """
    return (episode_id, step, EventType.ACT, Source.WORLD, action_chain(action))


def memory_write(episode_id: str, step: int, entry: StepMemory) -> AppendArgs:
    """把新写入的那条情景记忆拼成事件。"""
    return (
        episode_id, step, EventType.MEMORY_WRITE, Source.HARNESS,
        {"key": entry.key, "content": entry.render()},
    )


def object_note(episode_id: str, step: int, note: ObjectFact) -> AppendArgs:
    """语义记忆和情景记忆是两回事，分开写——见 `memory_write`。

    把一条语义记忆的更新拼成事件。
    """
    return (
        episode_id, step, EventType.OBJECT_NOTE, Source.HARNESS,
        {"key": note.landmark.place.key, "kind": note.landmark.kind,
         "content": note.render()},
    )


def goal_pop(episode_id: str, step: int, depth: int, goal: Goal, reason: str, why: str) -> AppendArgs:
    """一层目标判为完成、出栈。

    `reason` 目前只有 `done` 一个取值——曾经还有 `superseded`（中间层完成时，
    上面那些当初为它拆出来的一起作废），随多层判定一起删了。字段留着，
    因为拆解机制回来时"完成"和"白拆"仍然必须分得开，而那正是判断目标栈
    到底帮没帮上忙的那个数。

    配套的 `goal_push()` 也删了：压栈的唯一途径没有了，一个零生产者的纯函数
    只会让人以为图上还有那条路径。

    把一次目标出栈拼成事件。
    """
    return (
        episode_id, step, EventType.GOAL_POP, Source.JUDGE,
        {"depth": str(depth), "goal": goal.goal, "reason": reason, "why": why},
    )


# ---- 纯格式化，不单独对外暴露，供 observe() 用 ----

def _render_goal_stack(goals: list[Goal]) -> str:
    """把目标栈压成一行，塞进 `observe` 的 payload。**栈顶（当前要做的）在最后。**

    跟 `Brain._render_goals`（多行、给模型读、栈顶在最上面）刻意不同：
    一个是给人在日志里扫一眼查重复，一个是给模型逐行读的完整 prompt 片段，
    两者的读者和用途都不一样，没必要共用一份格式。

    把目标栈压成一行文本。
    """
    return " > ".join(f"[{depth}]{g.goal}" for depth, g in enumerate(goals))
