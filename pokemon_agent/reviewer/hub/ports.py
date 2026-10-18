"""命令层消费的进程内 API；查询异步，提交与取消在事件循环内原子完成。"""

from typing import Literal, Protocol

from pokemon_agent.schemas.reviewer import ViewAnswer, ViewQuery
from pokemon_agent.schemas.reviewer.interaction import (
    Ask,
    AuditAnswer,
    HistoryEntry,
    InjectAnswer,
    SubmitAck,
)


class CommandHub(Protocol):
    """命令只翻译输入，不维护第二套问的生命周期。"""

    def current(self, seq: int | None = None) -> Ask | None:
        """读当前问的独立快照；编号失效返回 None。"""
        ...

    def submit(
        self, seq: int, answer: InjectAnswer | AuditAnswer, by: Literal["human", "agent"]
    ) -> SubmitAck:
        """先答先得；旧编号和不匹配的答复正常拒绝，不抛。"""
        ...

    def accept_proposal(self, seq: int) -> SubmitAck:
        """由人工确认当前 AI 提案；没有待确认提案时明确拒绝。"""
        ...

    async def query(self, seq: int, q: ViewQuery) -> ViewAnswer:
        """查当前问材料；预期失败显式返回，查询不构成答复。"""
        ...

    def context(self, seq: int, section: str | None = None) -> ViewAnswer:
        """查看目录或指定节；未知节和失效编号正常拒绝。"""
        ...

    def history(self, n: int = 10) -> list[HistoryEntry]:
        """返回有限的独立历史摘要；n 非正时为空。"""
        ...

    def discuss(self, seq: int, text: str) -> SubmitAck:
        """讨论不是答复；没有 AI 席或问已失效时返回拒绝说明。"""
        ...
