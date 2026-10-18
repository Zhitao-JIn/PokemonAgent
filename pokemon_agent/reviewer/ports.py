"""进程内应用的装配契约；生产实现和测试替身满足同一组窄协议。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from pokemon_agent.schemas.reviewer import ViewAnswer
from pokemon_agent.schemas.reviewer.interaction import Ask, ReviewRequest, Settle, SubmitAck


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

    def show_result(self, seq: int, answer: ViewAnswer) -> None:
        """展示文字，图片仅保存 PNG 并打印路径尺寸；坏图正常报告失败。"""
        ...
