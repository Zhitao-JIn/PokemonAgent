"""链路消费的进程内提问能力，不认识 harness 或脑的实现。"""

from typing import Protocol

from pokemon_agent.schemas.reviewer.interaction import ReviewRequest, Settle


class QuestionHandler(Protocol):
    """取消协程必须解除其挂起问题，瞬时断线则保留协程等待重发。"""

    async def ask(self, req: ReviewRequest) -> Settle:
        """等待一次复核；正常答复或应用主动取消返回 Settle，任务取消向上传播。"""
        ...
