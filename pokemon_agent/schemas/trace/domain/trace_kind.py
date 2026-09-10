"""`TraceTool` 协议的账目词表：`TraceKind`。

一种 kind = 一种账。harness 组装 req 时声明"这是哪笔账"，`TraceTool` 按
kind 分派到对应的渲染函数（payload 字段格式归 tool 所有——跨模块契约，
观测台前端按字段名渲染，改字段必须同步前端）。

kind 与渲染函数一一对应；某 kind 必填哪些字段由渲染函数入口的
assert（precondition）表达，与 `TraceTool` 的 docstring 一一对应。
"""

from __future__ import annotations

from enum import StrEnum


class TraceKind(StrEnum):
    """一笔 trace 账的种类。命名与渲染函数一致，见 `tools/trace_render.py`。"""

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
    DECISION_FAILED = "decision_failed"

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
    LOOK_AFTER = "look_after"
    VERIFY_RESULT = "verify_result"
    PLAN_VERDICT = "plan_verdict"
    CHECKPOINT_RESTORE = "checkpoint_restore"
