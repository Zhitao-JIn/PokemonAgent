"""Reviewer 消费的窄读协议；实现从构造参数注入，不提供任何业务写方法。"""

from typing import Any, Protocol

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
    TraceEvent,
)
from pokemon_agent.schemas.reviewer import FrameQuery, RecallQuery, TraceQuery, ViewAnswer


class TraceReader(Protocol):
    """只查询事件；跨 run 的后端选择由实现负责，不能绑死在当前 run 的 trace_id。"""

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        """返回当前可见、满足全部 meta 等值条件的事件，不写账。

        实现须支持调用方指定的 run_id；可见性延迟须在装配时声明。
        预期读取失败抛 OSError / RuntimeError / ValueError，调用方不需预先排序。
        """
        ...


class MemoryReader(Protocol):
    """只查询记忆记录；允许服务端正常更新派生索引、向量缓存。"""

    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp:
        """返回原有 recall 语义的混合条目，limit=None 时必须保持全量。

        不调用 memorize、不改记录正文；允许刷新派生缓存（用户已授权）。
        预期读取失败抛 OSError / RuntimeError / ValueError；调用方须传合法请求模型。
        """
        ...


class ViewQueries(Protocol):
    """Hub 消费的三种同步查询；实现不持有当前问的状态。"""

    def read_trace(self, q: TraceQuery, *, default_run_id: str) -> ViewAnswer:
        """查询指定 run；预期失败返回 ok=False，不改写 trace。"""
        ...

    def recall(self, q: RecallQuery) -> ViewAnswer:
        """跨 run 探索记忆，不改正文；允许派生缓存刷新。"""
        ...

    def read_frame(self, q: FrameQuery, *, default_run_id: str) -> ViewAnswer:
        """显式读取历史画面；缺帧或坏帧正常返回失败。"""
        ...
