"""`*_CALL` 的批量落账：把一次交互的尝试账逐条摊成调用账。

从 `harness/trace_write.py` 搬入（D8-③ 定案）。**它本来就该在这一层**：
`FromHarnessToTraceToolAppendReq` 那条 docstring 写着"harness 只组装信封，tool 对
req 做处理（按 kind 渲染正文、**必要时一拆多**）"——而"一次交互的 N 次尝试 →
N 条调用账"正是那个"一拆多"。留一条这样的循环在 harness 里，等于让每个调用点
自己拆；搬上来之后，harness 侧只剩"攒账 + 交账"。

**`kind` 就是账名**（0914）：它一路落到封套上，渲染层不再给它换名字；
**链路名（`decide`…）是另一维**，由 `render._CALL_LINK` 给，只落进错误账的
`content.link`，所以这里只是把同一个 kind 原样传递下去，不做任何翻译。

**逐条摊而非一次交齐**：每次尝试单独组一个 `FromHarnessToTraceToolAppendReq`
（`calls=[call]`），事件流里的相对次序与"边重试边写"完全一致——重试循环期间
没有别的写账点。"第几次"由账落盘的先后顺序回答（0914 跟进删 `attempt` 戳）。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.tools.interface import TraceToolPort


def append_model_calls(
    trace: TraceToolPort, req: FromHarnessToTraceToolAppendModelCallsReq
) -> None:
    """把一次模型交互的尝试账逐条写进 trace。

    前置条件：`req.log` 按尝试顺序排列（重试循环保证）；空 log 是合法的
    （`ram_only=True` 的感知压根没调模型），那时什么也不写。
    后置条件：`req.log` 里每一条都已作为一条调用账落盘。
    """
    for call in req.log:
        trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=req.kind,
                meta=dict(req.meta),
                calls=[call],
            )
        )


__all__ = ["append_model_calls"]
