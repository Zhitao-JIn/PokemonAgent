"""单事件循环里的复核仲裁：一问挂起、先答先得、查询不算答复。"""

import asyncio
from collections import deque
from collections.abc import Callable
from typing import Literal

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectResp,
)
from pokemon_agent.schemas.harness.domain.review_context import frames_of
from pokemon_agent.schemas.reviewer import (
    BrainFramesQuery,
    FrameQuery,
    RecallQuery,
    TraceQuery,
    ViewAnswer,
    ViewQuery,
)
from pokemon_agent.schemas.reviewer.interaction import (
    Activity,
    Ask,
    AuditAnswer,
    HistoryEntry,
    InjectAnswer,
    ReviewProposal,
    ReviewRequest,
    Settle,
    SubmitAck,
)

from ..view.ports import ViewQueries
from ..view.render import text_without_frames
from .context import context_text

HISTORY_LIMIT: int = 50


class Hub:
    """调用方须在同一个 asyncio 事件循环使用全部方法，不跨线程修改状态。"""

    def __init__(
        self, readers: ViewQueries, *, on_activity: Callable[[Activity], None] | None = None
    ) -> None:
        self._readers = readers
        self._on_activity = on_activity
        self._seq = 0
        self._ask: Ask | None = None
        self._proposal: ReviewProposal | None = None
        self._future: asyncio.Future[Settle] | None = None
        self._history: deque[HistoryEntry] = deque(maxlen=HISTORY_LIMIT)
        self._activities: deque[Activity] = deque(maxlen=HISTORY_LIMIT)
        self._discuss_handler: Callable[[int, str], SubmitAck] | None = None

    def set_discuss_handler(self, handler: Callable[[int, str], SubmitAck]) -> None:
        """绑定应用层 AI 调度；只能在事件循环内调用。"""
        self._discuss_handler = handler

    def current(self, seq: int | None = None) -> Ask | None:
        """返回独立快照；旧编号看不到下一问的素材。"""
        if self._ask is None or (seq is not None and seq != self._ask.seq):
            return None
        return self._ask.model_copy(deep=True)

    def open_ask(self, req: ReviewRequest) -> asyncio.Future[Settle]:
        """挂起新问；前置条件是无未了结的问，返回 future 不允许外部取消内部承诺。"""
        assert self._ask is None, "only one review question may be pending"
        self._seq += 1
        self._ask = Ask(seq=self._seq, request=req.model_copy(deep=True))
        self._proposal = None
        self._future = asyncio.get_running_loop().create_future()
        try:
            self._record("open", f"{self._ask.kind} {req.context.run_id}")
        except BaseException:
            self._future.cancel()
            self._ask = None
            self._future = None
            raise
        return asyncio.shield(self._future)

    def submit(
        self, seq: int, answer: InjectAnswer | AuditAnswer, by: Literal["human", "agent"]
    ) -> SubmitAck:
        """只采纳当前问的第一份匹配答复，拒绝旧编号和不匹配的答复类型。"""
        ask = self.current(seq)
        if ask is None:
            return SubmitAck(ok=False, text="该问已了结")
        if by not in {"human", "agent"}:
            return SubmitAck(ok=False, text="无效答复来源")
        if ask.kind == "inject" and isinstance(answer, InjectAnswer):
            response = FromHarnessToReviewerInjectResp(text=answer.text, answered=True, by=by)
        elif ask.kind == "audit" and isinstance(answer, AuditAnswer):
            response = FromHarnessToReviewerAuditResp(**answer.model_dump(), answered=True, by=by)
        else:
            return SubmitAck(ok=False, text="该命令不适用于本问")
        self._finish(Settle(seq=seq, response=response))
        return SubmitAck(ok=True, text="已提交")

    def cancel(self, seq: int, reason: str = "该问已取消") -> SubmitAck:
        """显式取消唤醒等待方，取消不会变成默认认账。"""
        if self.current(seq) is None:
            return SubmitAck(ok=False, text="该问已了结")
        self._finish(Settle(seq=seq, cancelled=True, reason=text_without_frames(reason)))
        return SubmitAck(ok=True, text="已取消")

    async def query(self, seq: int, q: ViewQuery) -> ViewAnswer:
        """同步读取在线程池执行，返回前重核编号；查询期间仍可提交或取消本问。"""
        ask = self.current(seq)
        if ask is None:
            return ViewAnswer(ok=False, text="该问已了结")
        if isinstance(q, BrainFramesQuery):
            result = _brain_frames(ask, q)
        else:
            result = await asyncio.to_thread(self._read, ask, q)
        if self.current(seq) is None:
            return ViewAnswer(ok=False, text="该问已了结")
        self._record("query", q.tool)
        return result

    def context(self, seq: int, section: str | None = None) -> ViewAnswer:
        """展示当前问快照目录或指定节，节名非法不改变 pending。"""
        ask = self.current(seq)
        if ask is None:
            return ViewAnswer(ok=False, text="该问已了结")
        try:
            return ViewAnswer(ok=True, text=context_text(ask.request.context, section))
        except ValueError as exc:
            return ViewAnswer(ok=False, text=text_without_frames(str(exc)))

    def history(self, n: int = 10) -> list[HistoryEntry]:
        """返回最近 n 问的独立摘要，跨 run 保留，至多 HISTORY_LIMIT。"""
        if n <= 0:
            return []
        return [
            entry.model_copy(deep=True) for entry in list(self._history)[-min(n, HISTORY_LIMIT) :]
        ]

    def activities(self) -> list[Activity]:
        """活动也有界，不能无限保留查询历史。"""
        return [item.model_copy(deep=True) for item in self._activities]

    def discuss(self, seq: int, text: str) -> SubmitAck:
        """将人的增量意见交应用层调度 AI，不构成答复。"""
        if self.current(seq) is None:
            return SubmitAck(ok=False, text="该问已了结")
        if self._discuss_handler is None:
            return SubmitAck(ok=False, text="没有 AI 席")
        self._proposal = None
        return self._discuss_handler(seq, text)

    def stage_proposal(self, seq: int, proposal: ReviewProposal) -> SubmitAck:
        """暂存匹配当前问的 AI 答复，供人工在倒计时内明确采纳。"""
        ask = self.current(seq)
        if ask is None:
            return SubmitAck(ok=False, text="该问已了结")
        if not _proposal_matches(ask, proposal):
            return SubmitAck(ok=False, text="该提案不适用于本问")
        self._proposal = proposal.model_copy(deep=True)
        return SubmitAck(ok=True, text="AI 提案已准备好")

    def accept_proposal(self, seq: int) -> SubmitAck:
        """由人工确认并提交当前 AI 答复，答复来源记录为 human。"""
        if self.current(seq) is None:
            return SubmitAck(ok=False, text="该问已了结")
        if self._proposal is None:
            return SubmitAck(ok=False, text="当前没有可采纳的 AI 提案")
        proposal = self._proposal
        self._proposal = None
        return self.submit(seq, proposal.answer, "human")

    def propose(self, seq: int, proposal: ReviewProposal) -> SubmitAck:
        """只接受与当前问类型匹配的 AI 提案。"""
        return self.submit(seq, proposal.answer, "agent")

    def submit_default(self, seq: int) -> SubmitAck:
        """AI 无法作答时按无人值守契约返回默认值，明确标记 by=none。"""
        ask = self.current(seq)
        if ask is None:
            return SubmitAck(ok=False, text="该问已了结")
        if ask.kind == "inject":
            response = FromHarnessToReviewerInjectResp(text="", answered=False, by="none")
        else:
            response = FromHarnessToReviewerAuditResp(
                verdict=AuditVerdict.ACCEPT, note="", answered=False, by="none"
            )
        self._finish(Settle(seq=seq, response=response))
        return SubmitAck(ok=True, text="无人答复，采用默认结论")

    def _read(self, ask: Ask, q: TraceQuery | RecallQuery | FrameQuery) -> ViewAnswer:
        """只读操作不在工作线程里访问 hub 可变状态。"""
        run_id = ask.request.context.run_id
        if isinstance(q, TraceQuery):
            return self._readers.read_trace(q, default_run_id=run_id)
        if isinstance(q, RecallQuery):
            return self._readers.recall(q)
        return self._readers.read_frame(q, default_run_id=run_id)

    def _finish(self, settle: Settle) -> None:
        """前置条件：当前问存在且内部 future 未完成；先解除占用再唤醒等待方。"""
        ask, future = self._ask, self._future
        assert ask is not None and future is not None and not future.done()
        prompt = ask.request.prompt if ask.kind == "inject" else "复核已达成结论"
        self._history.append(
            HistoryEntry(
                seq=ask.seq,
                kind=ask.kind,
                run_id=ask.request.context.run_id,
                prompt=text_without_frames(prompt),
                settle=settle.model_copy(deep=True),
            )
        )
        self._ask = None
        self._proposal = None
        self._future = None
        future.set_result(settle)
        self._record(
            "cancel" if settle.cancelled else "submit", settle.reason or "已提交", seq=settle.seq
        )

    def _record(self, action: str, text: str, *, seq: int | None = None) -> None:
        """只在事件循环内记活动，可注入终端通知回调。"""
        assert seq is not None or self._ask is not None
        number = seq if seq is not None else self._ask.seq
        event = Activity(seq=number, action=action, text=text_without_frames(text))
        self._activities.append(event)
        if self._on_activity is not None:
            self._on_activity(event.model_copy(deep=True))


def _brain_frames(ask: Ask, q: BrainFramesQuery) -> ViewAnswer:
    """按随问快照原顺序分页，不查询共享读端口，不套大脑的图上限。"""
    frames = frames_of(ask.request.context.brain_input)
    page = frames[q.offset : q.offset + q.limit]
    span = f"第 {q.offset + 1}–{q.offset + len(page)} 张" if page else "0 张"
    text = f"共 {len(frames)} 张，本次{span}\n" + "\n".join(label for label, _ in page)
    return ViewAnswer(ok=True, text=text_without_frames(text), images=[frame for _, frame in page])


def _proposal_matches(ask: Ask, proposal: ReviewProposal) -> bool:
    """拒绝与固定问题类型不匹配的暂存提案。"""
    if ask.kind == "inject":
        return isinstance(proposal.answer, InjectAnswer)
    return isinstance(proposal.answer, AuditAnswer)
