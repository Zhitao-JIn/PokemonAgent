"""Reviewer 消费的窄读协议；实现从构造参数注入，不提供任何业务写方法。"""

from typing import Any, Protocol

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToMemoryToolRecallResp,
    TraceEvent,
)


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
