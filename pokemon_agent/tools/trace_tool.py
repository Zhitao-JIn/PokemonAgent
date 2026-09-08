"""`TraceToolPort` 的唯一实现：harness 和事件流之间那层"记账处理"。

持有 `TracePort`（事件流存储）。`append()` 做两件事：按 `req.kind` 分派到
`trace_render.py` 的渲染函数（payload 字段格式、条件字段、一拆多全在这层），
再把渲染结果交给 `TracePort.append()` 落盘；`events()` 原样转发——读侧没有
要转换的数据（调用方拿的是存储形状 `TraceEvent`，跟 `MemoryToolPort` 返回
领域对象同一个模式）。

**payload 字段格式是跨模块契约**：`evaluation/eval_report.py` 按字段名解析，
格式变更权在本层（见 `trace_render.py` 模块 docstring）。

**边界不对称**：写者只有 harness（走本端口）；读者是 api/evaluation
（运维侧，直读 `TracePort`/`LocalTrace`，不进 tool 层）。
"""

from __future__ import annotations

from collections.abc import Iterable

from pokemon_agent.interfaces import TracePort
from pokemon_agent.schemas.communication import (
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.tools import trace_render

_RENDERERS = {
    TraceKind.RUN_START: trace_render.run_start,
    TraceKind.RUN_END: trace_render.run_end,
    TraceKind.RUN_ERROR: trace_render.run_error,
    TraceKind.EPISODE_START: trace_render.episode_start,
    TraceKind.EPISODE_END: trace_render.episode_end,
    TraceKind.EPISODE_ERROR: trace_render.episode_error,
    TraceKind.MODEL_CALL: trace_render.model_call,
    TraceKind.JUDGE_CALL: trace_render.judge_call,
    TraceKind.VERIFY_CALL: trace_render.verify_call,
    TraceKind.DECISION_FAILED: trace_render.decision_failed,
    TraceKind.PERMISSION_SKIPPED: trace_render.permission_skipped,
    TraceKind.OBSERVE: trace_render.observe,
    TraceKind.MEMORY_READ: trace_render.memory_read,
    TraceKind.MEMORY_WRITE: trace_render.memory_write,
    TraceKind.OBJECT_NOTE: trace_render.object_note,
    TraceKind.EPISODE_MEMORY_WRITE: trace_render.episode_memory_write,
    TraceKind.EPISODE_SUMMARY_ERROR: trace_render.episode_summary_error,
    TraceKind.THINK: trace_render.think,
    TraceKind.ACT: trace_render.act,
    TraceKind.STALL_CHECK: trace_render.stall_check,
    TraceKind.HUMAN_NOTE_INJECTED: trace_render.human_note_injected,
    TraceKind.JUDGE_VERDICT: trace_render.judge_verdict,
    TraceKind.ACTION_SPACE: trace_render.action_space,
    TraceKind.RETRIEVE_NODE: trace_render.retrieve_node,
    TraceKind.STEP_ADVANCE: trace_render.step_advance,
    TraceKind.LOOK_AFTER: trace_render.look_after,
    TraceKind.VERIFY_RESULT: trace_render.verify_result,
    TraceKind.PLAN_VERDICT: trace_render.plan_verdict,
    TraceKind.CHECKPOINT_RESTORE: trace_render.checkpoint_restore,
}


class TraceTool:
    """`TraceToolPort` 的唯一实现。持有事件流存储（或任何 `TracePort` 实现）。

    **本对象没有状态**——按 kind 分派 + 落盘，全部输入来自参数。
    """

    def __init__(self, trace: TracePort) -> None:
        """接好事件流存储。"""
        self._trace = trace

    def append(self, req: FromHarnessToTraceToolAppendReq) -> int:
        """记一笔账：按 `req.kind` 渲染 payload，逐条落盘。

        前置条件：req.kind 对应的渲染函数所需字段非空（各渲染函数入口
        assert 就地爆炸）。
        后置条件：所有渲染出的事件已落盘；返回最后一条分到的 event_id
        （严格大于此前任何一次 append 的值，`TracePort.append` 保证）。
        """
        renderer = _RENDERERS[req.kind]
        last_id = 0
        for event_type, source, payload in _as_list(renderer(req)):
            last_id = self._trace.append(
                req.episode_id,
                req.step,
                event_type,
                source,
                payload,
                frame_png=req.frame_png,
                screenshot_step=req.screenshot_step,
            )
        return last_id

    def read_disk_events(self) -> list:
        """读盘上全部事件（原样转发 `TracePort.read_disk_events`，checkpoint 恢复用）。"""
        return self._trace.read_disk_events()

    def cursor(self) -> int:
        """当前游标：最后一条已分配的 event_id（原样转发 `TracePort.cursor`）。"""
        return self._trace.cursor()


def _as_list(rendered) -> Iterable:
    """渲染函数的返回值归一：单三元组或三元组列表，统一成可迭代。"""
    if isinstance(rendered, list):
        return rendered
    return [rendered]
