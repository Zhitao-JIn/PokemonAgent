"""`MODEL_CALL` 的批量落账：把一次交互的尝试账逐条摊成 `MODEL_CALL` 事件。

从 `harness/trace_write.py` 搬入（D8-③ 定案）。**它本来就该在这一层**：
`FromHarnessToTraceToolAppendReq` 那条 docstring 写着"harness 只组装信封，tool 对
req 做处理（按 kind 渲染 payload、**必要时一拆多**）"——而"一次交互的 N 次尝试 →
N 条 `MODEL_CALL`"正是那个"一拆多"。留一条这样的循环在 harness 里，等于让每个
调用点自己拆；搬上来之后，harness 侧只剩"攒账 + 交账"。

**顺序即尝试顺序**：同一次尝试可能吐多条事件（`render.model_call` 会为带
`error_kind` 的账补一条 ERROR），但事件流里的相对次序与"边重试边写"完全一致
——重试循环期间没有别的写账点，`event_id` 的相对次序不变。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.tools.interface import TraceToolPort


def append_model_calls(
    trace: TraceToolPort, req: FromHarnessToTraceToolAppendModelCallsReq
) -> None:
    """把一次模型交互的尝试账逐条写进 trace。

    前置条件：`req.log` 的 `attempt` 升序（重试循环保证）；空 log 是合法的
    （`ram_only=True` 的感知压根没调模型），那时什么也不写。
    后置条件：`req.log` 里每一条都已作为一条 `MODEL_CALL` 落盘。
    """
    for attempt, call in req.log:
        trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.MODEL_CALL,
                episode_id=req.episode_id,
                step=req.step,
                source=req.source,
                calls=[call],
                attempt=attempt,
            )
        )


__all__ = ["append_model_calls"]
