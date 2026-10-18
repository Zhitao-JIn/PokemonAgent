"""R6a 的进程内 human 应用；网络入口与读端口装配由 R6b 接入。"""

import asyncio

from pokemon_agent.schemas.reviewer.interaction import ReviewRequest, ReviewSeats, Settle

from .ports import AppHub, CommandRunner, HumanTerminal


class ReviewerApp:
    """依赖全部注入，human 席与 hub 必须使用同一个事件循环；本阶段不接受 AI 配置。"""

    def __init__(
        self, seats: ReviewSeats, *, hub: AppHub, commands: CommandRunner, human: HumanTerminal
    ) -> None:
        if not seats.human or seats.ai:
            raise ValueError("R6a 仅支持 human 席；AI 席在 R7 接入")
        self._hub = hub
        self._commands = commands
        self._human = human
        self._closed = False

    async def ask(self, req: ReviewRequest) -> Settle:
        """挂起一问并展示；调用方取消时同样取消 hub pending，不伪造答复。"""
        if self._closed:
            raise RuntimeError("reviewer 应用已关闭")
        future = self._hub.open_ask(req)
        ask = self._hub.current()
        assert ask is not None
        try:
            self._human.show_ask(ask)
            return await future
        finally:
            if self._hub.current(ask.seq) is not None:
                self._hub.cancel(ask.seq, "提问调用方已退出")

    async def serve(self) -> None:
        """消费注入的终端行源；每条命令绑定输入时的 seq，EOF 或取消解除 pending。"""
        tasks: set[asyncio.Task[None]] = set()
        try:
            self._human.prompt(self._hub.current())
            async with asyncio.TaskGroup() as group:
                try:
                    async for line in self._human:
                        ask = self._hub.current()
                        task = group.create_task(self._execute(ask.seq if ask else 0, line))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                        await asyncio.sleep(0)
                finally:
                    self.close()
                    for task in tasks:
                        task.cancel()
        finally:
            self.close()

    async def _execute(self, seq: int, line: str) -> None:
        """查询等待期间继续读人的输入；完成后重新展示当前问的提示符。"""
        answer = await self._commands.execute(seq, line)
        self._human.show_result(seq, answer)
        self._human.prompt(self._hub.current())

    def close(self) -> None:
        """幂等关闭，所有等待方收到显式取消；正在运行的 serve 由调用方取消。"""
        if self._closed:
            return
        self._closed = True
        ask = self._hub.current()
        if ask is not None:
            self._hub.cancel(ask.seq, "reviewer 应用已关闭")
