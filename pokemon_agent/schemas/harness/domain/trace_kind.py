"""**harness 的账目词表**：`TraceKind`。

一种 kind = 一种账。harness 组装 `FromHarnessToTraceToolAppendReq` 时声明
"这是哪笔账"，`TraceTool` 按 kind 分派到对应的渲染函数。

**归属看谁消费**（0913 定案）：`TraceKind` 的消费者是 **harness**——
22 个 harness 节点各自声明自己记什么账，`schemas/harness/communication/` 的
`FromHarnessToTraceToolAppendReq` 把它装进信封。所以它归 `schemas/harness/`，
跟"harness 只认 schemas"这条边界一致：harness 不再 import `trace` 包拿自己的词表。

**它曾经住在 `pokemon_agent/trace/interface/domain/`**，理由是"跟 `TracePort`
归一处 / 跟 `Facts`/`WorldPort` 搬家同理"。那个类比是错的：`Facts`/`WorldPort`
的消费者是它们自己那层的实现，而 `TraceKind` 的消费者是 harness。搬到这里之后
harness 侧的 import 从 `from pokemon_agent.trace import TraceKind` 变成
`from pokemon_agent.schemas.harness import TraceKind`——**依赖方向上也更干净**
（harness 依赖契约，不依赖 tool 的实现包）。

**两件事分得清**：`TraceKind`（有哪几种账要记）归 harness；
**每种账的 payload 字段名**（这笔账长什么样）归 tool 的渲染层
（`tools/trace/render.py`）——那是跨模块契约，观测台前端按字段名渲染。
"""

from __future__ import annotations

from enum import StrEnum


class TraceKind(StrEnum):
    """一笔 trace 账的种类。命名与渲染函数一致，见 `tools/trace/render.py`。"""

    # run 边界（episode_id 位放 run_id、step 恒 0）
    RUN_START = "run_start"
    RUN_END = "run_end"
    RUN_ERROR = "run_error"

    # episode 边界
    EPISODE_START = "episode_start"
    EPISODE_END = "episode_end"
    EPISODE_ERROR = "episode_error"

    # 账：模型调用（可能一拆多：账单 + 失败补 ERROR）
    MODEL_CALL = "model_call"
    JUDGE_CALL = "judge_call"
    VERIFY_CALL = "verify_call"
    SUMMARY_CALL = "summary_call"

    # 节点失败（重试预算耗尽）：**只回答"这个节点完了、为什么"，不带账**。
    # 账归上面的 MODEL_CALL——两条关注点分开记（0913 定案）。
    # 五条链路各一种，`source` 与 kind 一一对应。
    DECISION_FAILED = "decision_failed"
    PLAN_FAILED = "plan_failed"
    JUDGE_FAILED = "judge_failed"
    VERIFY_FAILED = "verify_failed"
    SUMMARIZE_FAILED = "summarize_failed"

    # 一步之内的事件
    OBSERVE = "observe"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    OBJECT_NOTE = "object_note"
    EPISODE_MEMORY_WRITE = "episode_memory_write"
    EPISODE_SUMMARY_ERROR = "episode_summary_error"
    THINK = "think"
    ACT = "act"
    STALL_CHECK = "stall_check"
    HUMAN_NOTE_INJECTED = "human_note_injected"

    # 节点活动轻量事件（不经模型）
    JUDGE_VERDICT = "judge_verdict"
    ACTION_SPACE = "action_space"
    RETRIEVE_NODE = "retrieve_node"
    STEP_ADVANCE = "step_advance"
    AFTER_ACTION = "after_action"
    ACTION_TRUNCATED = "action_truncated"
    VERIFY_RESULT = "verify_result"
    PLAN_VERDICT = "plan_verdict"
