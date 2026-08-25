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
from pokemon_agent.schemas.memory_episode import EpisodeMemory
from pokemon_agent.schemas.memory_episodic import MemoryEntry
from pokemon_agent.schemas.memory_semantic import ObjectFact
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


# ---- 一步之内的各类事件 ----

def observe(episode_id: str, obs: Observation, goals: list[Goal], frame_sha: str) -> AppendArgs:
    """**facts 必须进 payload。** 它才是观测的实质内容。只记 summary 的话，
    replay 出来只剩「你在野外」这种废话。

    `frame_sha` 同样关键：没有它，一条读错的观测**无法追查**是哪一帧。

    **`goals` 也要跟着这一帧一起记**——以前目标栈只在 `GOAL_PUSH`/`GOAL_POP`
    事件里出现过一次，读日志的人拿不到"这一帧、这个决策，当时的栈长什么样"。

    把这一帧观测拼成事件。
    """
    return (
        episode_id, obs.step, EventType.OBSERVE, Source.PERCEPTION,
        {"frame_sha": frame_sha, "summary": obs.summary,
         "scene": obs.facts.get("scene", ""), "overlay": obs.facts.get("overlay", ""),
         "facts": json.dumps(obs.facts, ensure_ascii=False),
         "goals": _render_goal_stack(goals)},
    )


def memory_read(
    episode_id: str, step: int, memories: list[MemoryEntry],
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
        payload["known_object_names"] = _short_labels(known_objects)
        payload["known_objects_chars"] = str(len(known_objects))
    if knowledge:
        payload["knowledge"] = "1"
        payload["knowledge_sources"] = " ".join(knowledge_sources)
    if episode_memories:
        payload["episode_memory_count"] = str(len(episode_memories))
        payload["episode_level_count"] = str(len(episode_memories))
        payload["episode_memory_refs"] = " ".join(m.episode_id for m in episode_memories)
    return (episode_id, step, EventType.MEMORY_READ, Source.DECISION, payload)


def _short_labels(text: str, limit: int = 5) -> str:
    """从多段渲染文本取每段第一行，作为观测台的短标签。

    取每段渲染文本的首行当短标签。
    """
    labels: list[str] = []
    for block in text.split("\n\n"):
        first = next((line.strip() for line in block.splitlines() if line.strip()), "")
        first = first.lstrip("# ").strip()
        if first and first not in labels:
            labels.append(first[:80])
        if len(labels) >= limit:
            break
    return " | ".join(labels)


def think(episode_id: str, step: int, action: Action, attempt: int) -> AppendArgs:
    """把这一步选出的动作拼成事件。"""
    return (
        episode_id, step, EventType.THINK, Source.DECISION,
        {"thought": action.thought, "action": action.name,
         # args 必须记：不记的话分不清「模型没给参数」和「给了但没显示」。
         "args": json.dumps(action.args, ensure_ascii=False),
         # rationale 也记在这里，不只依赖 MEMORY_WRITE——
         # **无记忆基线组不写记忆**，那时 rationale 只剩这一处落点。
         "rationale": json.dumps(action.rationale, ensure_ascii=False),
         "attempt": str(attempt)},
    )


def act(episode_id: str, step: int, action: Action, message: str) -> AppendArgs:
    """把这一次按键的结果拼成事件。"""
    return (
        episode_id, step, EventType.ACT, Source.WORLD,
        {"action": action.name, "args": json.dumps(action.args, ensure_ascii=False),
         "message": message},
    )


def memory_write(episode_id: str, step: int, entry: MemoryEntry) -> AppendArgs:
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


def inspect(episode_id: str, step: int, focus: str, answer: str) -> AppendArgs:
    """和 `observe` 分开：这是大脑主动要的，不是每步必发的那一帧。

    把一次细看拼成事件。
    """
    return (
        episode_id, step, EventType.INSPECT, Source.PERCEPTION,
        {"focus": focus, "answer": answer},
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
