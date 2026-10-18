"""reviewer 进程内 human / AI 应用与问题生命周期。"""

import asyncio

from pokemon_agent.schemas.reviewer.interaction import (
    Ask,
    AuditAnswer,
    ReviewProposal,
    ReviewRequest,
    ReviewSeats,
    Settle,
    SubmitAck,
)

from .ports import AiReviewer, AppHub, CommandRunner, HumanTerminal


class ReviewerApp:
    """依赖全部注入，AI 与 hub 共享事件循环，human 行源可选。"""

    def __init__(
        self,
        seats: ReviewSeats,
        *,
        hub: AppHub,
        commands: CommandRunner,
        human: HumanTerminal | None,
        ai: AiReviewer | None = None,
        countdown_s: int,
    ) -> None:
        if seats.human != (human is not None) or seats.ai != (ai is not None):
            raise ValueError("启用的席位必须且只能注入对应实现")
        self._hub = hub
        self._commands = commands
        self._human = human
        self._ai = ai
        self._countdown_s = countdown_s
        self._closed = False
        self._ai_task: asyncio.Task[None] | None = None
        if ai is not None:
            hub.set_discuss_handler(self._discuss)

    async def ask(self, req: ReviewRequest) -> Settle:
        """挂起一问并展示；调用方取消时同样取消 hub pending，不伪造答复。"""
        if self._closed:
            raise RuntimeError("reviewer 应用已关闭")
        future = self._hub.open_ask(req)
        ask = self._hub.current()
        assert ask is not None
        try:
            if self._human is not None:
                self._human.show_ask(ask)
            if self._ai is not None:
                self._ai_task = asyncio.create_task(self._run_ai(ask))
            return await future
        finally:
            self._cancel_ai()
            if self._hub.current(ask.seq) is not None:
                self._hub.cancel(ask.seq, "提问调用方已退出")

    async def serve(self) -> None:
        """消费注入的终端行源；每条命令绑定输入时的 seq，EOF 或取消解除 pending。"""
        if self._human is None:
            return
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
        self._cancel_ai()
        ask = self._hub.current()
        if ask is not None:
            self._hub.cancel(ask.seq, "reviewer 应用已关闭")

    async def _run_ai(self, ask: Ask, human_note: str = "") -> None:
        """AI 失败只影响本问；ai-only 用 none 让 run 按既有默认继续。"""
        assert self._ai is not None
        proposal = await self._ai.run_turn(ask, human_note)
        if self._hub.current(ask.seq) is None:
            return
        if proposal is None:
            if self._human is None:
                self._hub.submit_default(ask.seq)
            return
        if self._human is None:
            self._hub.propose(ask.seq, proposal)
            return
        self._hub.stage_proposal(ask.seq, proposal)
        self._human.show_proposal(ask, _proposal_text(proposal), self._countdown_s)
        try:
            await asyncio.sleep(self._countdown_s)
        except asyncio.CancelledError:
            return
        if self._hub.current(ask.seq) is not None:
            self._hub.propose(ask.seq, proposal)

    def _discuss(self, seq: int, text: str) -> SubmitAck:
        """人的 ask-ai 取消当前提案窗口并开启带增量意见的新轮。"""
        ask = self._hub.current(seq)
        if ask is None or self._ai is None:
            return SubmitAck(ok=False, text="该问已了结" if ask is None else "没有 AI 席")
        self._cancel_ai()
        self._ai_task = asyncio.create_task(self._run_ai(ask, text))
        return SubmitAck(ok=True, text="已让 AI 重新复核")

    def _cancel_ai(self) -> None:
        """问结束后停止该问 AI 请求，避免迟到结果进入下一问。"""
        if self._ai_task is not None and not self._ai_task.done():
            self._ai_task.cancel()
        self._ai_task = None


def _proposal_text(proposal: ReviewProposal) -> str:
    """把结构化 AI 答复转成供人阅读的内容，不展示传输信封。"""
    answer = proposal.answer
    if isinstance(answer, AuditAnswer):
        verdict = "认账" if answer.verdict.value == "accept" else "推翻"
        return verdict if not answer.note else f"{verdict}：{answer.note}"
    return answer.text
