"""独立评分器消费的最小模型契约。"""

from typing import Protocol

from inspect_ai.model import ChatMessage


class ReviewReply(Protocol):
    """评分文本；传输元数据继续由 Inspect 自身记录。"""

    @property
    def completion(self) -> str:
        """返回模型原始完整文本；不能预先吞掉解析失败。"""
        ...


class ReviewProvider(Protocol):
    """保留完整消息的独立模型；网络错误原样上抛，不视为格式问题。"""

    async def generate(self, messages: list[ChatMessage], /) -> ReviewReply:
        """调用方交齐规则和素材；返回原始文本或抛传输异常。"""
        ...
