"""进程内应用的装配契约；生产实现和测试替身满足同一组窄协议。"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Literal, Protocol

from pokemon_agent.schemas.reviewer import ViewAnswer
from pokemon_agent.schemas.reviewer.interaction import (
    Ask,
    AuditAnswer,
    InjectAnswer,
    ReviewProposal,
    ReviewRequest,
    Settle,
    SubmitAck,
)


class AiReviewer(Protocol):
    """reviewer 进程内的 AI 席；不向应用泄露模型 SDK 类型。"""

    async def run_turn(self, ask: Ask, human_note: str = "") -> ReviewProposal | None:
        """为当前问形成候选答复；模型失败返回 None，可由调用方取消。"""
        ...


class AppHub(Protocol):
    """应用只负责挂问与关闭，不复制仲裁逻辑。"""

    def open_ask(self, req: ReviewRequest) -> asyncio.Future[Settle]:
        """挂起一问，调用方保证当前无 pending；future 取消不改变内部结果。"""
        ...

    def current(self, seq: int | None = None) -> Ask | None:
        """返回当前问独立快照；旧编号正常返回 None。"""
        ...

    def cancel(self, seq: int, reason: str = "该问已取消") -> SubmitAck:
        """取消唤醒等待方；旧编号正常拒绝，不伪造认账。"""
        ...

    def submit(
        self,
        seq: int,
        answer: AuditAnswer | InjectAnswer,
        by: Literal["human", "agent"],
    ) -> SubmitAck:
        """提交匹配问种类的答复；过期编号明确拒绝。"""
        ...

    def propose(self, seq: int, proposal: ReviewProposal) -> SubmitAck:
        """提交 AI 候选答复；hub 再次校验当前问与答复类型。"""
        ...

    def submit_default(self, seq: int) -> SubmitAck:
        """以 by=none 结算无人答复；过期编号明确拒绝。"""
        ...

    def set_discuss_handler(self, handler: Callable[[int, str], SubmitAck]) -> None:
        """绑定应用层 AI 调度回调，人的讨论仍由 hub 校验当前 qid。"""
        ...


class CommandRunner(Protocol):
    """每行显式绑定问题编号，正常输入错误返回说明，不抛。"""

    async def execute(self, seq: int, line: str) -> ViewAnswer:
        """解析并执行一行；查询可能等待，但不能修改问题编号。"""
        ...


class HumanTerminal(Protocol):
    """终端输入、展示与图片副产物，不持有仲裁状态。"""

    def __aiter__(self) -> AsyncIterator[str]:
        """异步输入行；EOF 结束，输入异常向应用传播。"""
        ...

    def show_ask(self, ask: Ask) -> None:
        """展示本问提案和帮助入口，文本不得带图片编码。"""
        ...

    def prompt(self, ask: Ask | None) -> None:
        """显示当前问或空闲提示；不产生答复。"""
        ...

    def show_proposal(self, ask: Ask, proposal: str, countdown_s: int) -> None:
        """展示 AI 提案与倒计时，供人席接管。"""
        ...

    def show_result(self, seq: int, answer: ViewAnswer) -> None:
        """展示文字，图片仅保存 PNG 并打印路径尺寸；坏图正常报告失败。"""
        ...
