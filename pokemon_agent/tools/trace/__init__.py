"""`TraceToolPort` 的唯一实现：harness 和事件流之间那层"记账处理"。

持有 `TracePort`（事件流存储）。两个写方法分工一致——**调用方只组装信封，拆解规则
在本层**：

- `append()`：一笔账 → 按 `req.kind` 分派到 `render.py` 的渲染函数（payload 字段
  格式、条件字段全在这层），一 req 可能渲成多条事件（账单 + 失败补 ERROR）；
- `append_model_calls()`：一次模型交互的 N 次尝试 → N 条 `MODEL_CALL`，拆解规则在
  `model_calls.py`。

`read_disk_events()` / `cursor()` / `void_after()` 原样转发——读侧与废弃打标都没有
要转换的数据（调用方拿的是存储形状 `TraceEvent`，跟 `MemoryToolPort` 返回领域对象
同一个模式；`void_after` 返回的"整局废弃名单"也是存储层的直接产物）。

**payload 字段格式是跨模块契约**：观测台前端按字段名渲染，格式变更权在本层（见
`render.py` 模块 docstring）。

**边界不对称**：写者只有 harness（走本端口）；读者是 api
（运维侧，直读 `TracePort`/`LocalTrace`，不进 tool 层）。

**本包收拢三个 trace 相关文件**（与 `harness/episode/` 同款手法）：`__init__.py`
（分派器 + 端口实现）、`render.py`（每种账的 payload，30 个纯函数）、`model_calls.py`
（批量账）。为什么合包不合并：`render.py` 动一次就是跨模块契约变更、`__init__.py`
动一次只是"多一种 kind"，变更触发条件不同，混一起会让"我这次改的是不是契约"变模糊。
"""

from __future__ import annotations

from collections.abc import Iterable

from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    FromHarnessToTraceToolReadDiskEventsReq,
    FromHarnessToTraceToolReadDiskEventsResp,
    FromHarnessToTraceToolVoidAfterReq,
)
from pokemon_agent.trace import TraceKind, TracePort

from . import model_calls, render

_RENDERERS = {
    TraceKind.RUN_START: render.run_start,
    TraceKind.RUN_END: render.run_end,
    TraceKind.RUN_ERROR: render.run_error,
    TraceKind.EPISODE_START: render.episode_start,
    TraceKind.EPISODE_END: render.episode_end,
    TraceKind.EPISODE_ERROR: render.episode_error,
    TraceKind.MODEL_CALL: render.model_call,
    TraceKind.JUDGE_CALL: render.judge_call,
    TraceKind.VERIFY_CALL: render.verify_call,
    TraceKind.DECISION_FAILED: render.decision_failed,
    TraceKind.OBSERVE: render.observe,
    TraceKind.MEMORY_READ: render.memory_read,
    TraceKind.MEMORY_WRITE: render.memory_write,
    TraceKind.OBJECT_NOTE: render.object_note,
    TraceKind.EPISODE_MEMORY_WRITE: render.episode_memory_write,
    TraceKind.EPISODE_SUMMARY_ERROR: render.episode_summary_error,
    TraceKind.THINK: render.think,
    TraceKind.ACT: render.act,
    TraceKind.STALL_CHECK: render.stall_check,
    TraceKind.HUMAN_NOTE_INJECTED: render.human_note_injected,
    TraceKind.JUDGE_VERDICT: render.judge_verdict,
    TraceKind.ACTION_SPACE: render.action_space,
    TraceKind.RETRIEVE_NODE: render.retrieve_node,
    TraceKind.STEP_ADVANCE: render.step_advance,
    TraceKind.AFTER_ACTION: render.after_action,
    TraceKind.ACTION_TRUNCATED: render.action_truncated,
    TraceKind.VERIFY_RESULT: render.verify_result,
    TraceKind.PLAN_VERDICT: render.plan_verdict,
    TraceKind.CHECKPOINT_RESTORE: render.checkpoint_restore,
    TraceKind.CHECKPOINT_SAVE: render.checkpoint_save,
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
            )
        return last_id

    def append_model_calls(self, req: FromHarnessToTraceToolAppendModelCallsReq) -> None:
        """记一次模型交互的**全部尝试**：一笔交互 → N 条 `MODEL_CALL`。

        与 `append` 同一分工——调用方只组装信封（定位字段 + `source` + 原始尝试账），
        "每条带什么 `attempt`、怎么落"是本层的事（`model_calls.append_model_calls`）。

        前置条件：`req.log` 按 `attempt` 升序（重试循环保证）。
        后置条件：`req.log` 里每一条都已落盘；空 log 合法且不写任何事件。
        """
        model_calls.append_model_calls(self, req)

    def read_disk_events(
        self, req: FromHarnessToTraceToolReadDiskEventsReq
    ) -> FromHarnessToTraceToolReadDiskEventsResp:
        """读盘上全部事件（原样转发 `TracePort.read_disk_events`，checkpoint 恢复用）。"""
        return FromHarnessToTraceToolReadDiskEventsResp(events=self._trace.read_disk_events())

    def cursor(self) -> int:
        """当前游标：最后一条已分配的 event_id（原样转发 `TracePort.cursor`）。"""
        return self._trace.cursor()

    def void_after(self, req: FromHarnessToTraceToolVoidAfterReq) -> list[str]:
        """把游标之后的事件作废，返回**整局废弃**的局列表（原样转发 `TracePort.void_after`）。

        打标规则与"哪些局只活在游标之后"都是存储层的知识（见 `TracePort.void_after`），
        本层没有要转换的东西——调用方（`episode_entry.void_timeline`）拿到名单后去作废
        对应的记忆与存档，那是恢复语义。
        """
        return self._trace.void_after(req.cursor)


def _as_list(rendered) -> Iterable:
    """渲染函数的返回值归一：单三元组或三元组列表，统一成可迭代。"""
    if isinstance(rendered, list):
        return rendered
    return [rendered]


__all__ = ["TraceTool"]
