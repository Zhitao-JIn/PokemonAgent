"""复核仲裁的用法：先答先得，取消唤醒，查询保持同一问，历史与输入均隔离。"""

import asyncio
import threading
from typing import Any

import pytest
from _doubles.reviewer import audit_request, inject_request
from pydantic import ValidationError

from pokemon_agent.reviewer.hub import Hub
from pokemon_agent.reviewer.view import ViewReaders
from pokemon_agent.schemas.harness import AuditVerdict, TraceEvent
from pokemon_agent.schemas.reviewer import BrainFramesQuery, TraceQuery
from pokemon_agent.schemas.reviewer.interaction import (
    AuditAnswer,
    InjectAnswer,
    ReviewSeats,
    Settle,
    SubmitAck,
)


def test_first_matching_answer_wins_and_external_mutation_cannot_rewrite_history() -> None:
    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        request = inject_request()
        future = hub.open_ask(request)
        request.prompt = "外部修改"
        assert hub.current().request.prompt == "请看提案"
        assert not hub.submit(1, AuditAnswer(), "human").ok
        assert not hub.submit(999, InjectAnswer(text="stale"), "human").ok
        assert hub.submit(1, InjectAnswer(text="winner"), "human").ok
        assert not hub.submit(1, InjectAnswer(text="late"), "agent").ok
        result = await future
        assert result.response.text == "winner" and result.response.by == "human"
        result.response.text = "mutated"
        assert hub.history()[0].settle.response.text == "winner"
        history = hub.history()
        history[0].prompt = "changed"
        assert hub.history()[0].prompt == "请看提案"

    asyncio.run(scenario())


def test_audit_overturn_and_cancel_are_distinct_resolutions() -> None:
    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        future = hub.open_ask(audit_request())
        assert not hub.submit(1, InjectAnswer(text="wrong"), "human").ok
        assert hub.submit(1, AuditAnswer(verdict=AuditVerdict.OVERTURN, note="未达成"), "human").ok
        assert (await future).response.note == "未达成"
        pending = hub.open_ask(inject_request())
        assert hub.cancel(2, "断开").ok
        result = await pending
        assert result.cancelled and result.response is None and result.reason == "断开"
        assert not hub.cancel(2).ok

    asyncio.run(scenario())


def test_human_can_accept_the_staged_ai_proposal_for_either_question_kind() -> None:
    from pokemon_agent.schemas.reviewer.interaction import ReviewProposal

    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        inject_future = hub.open_ask(inject_request())
        inject_proposal = ReviewProposal(answer=InjectAnswer(text="按 AI 建议移动"))

        assert not hub.accept_proposal(1).ok
        assert not hub.stage_proposal(1, ReviewProposal(answer=AuditAnswer(verdict="accept"))).ok
        assert hub.stage_proposal(1, inject_proposal).ok
        assert hub.accept_proposal(1).ok
        inject_result = await inject_future
        assert inject_result.response.text == "按 AI 建议移动"
        assert inject_result.response.by == "human"

        audit_future = hub.open_ask(audit_request())
        audit_proposal = ReviewProposal(answer=AuditAnswer(verdict="overturn", note="证据不足"))

        assert hub.stage_proposal(2, audit_proposal).ok
        assert hub.accept_proposal(2).ok
        audit_result = await audit_future
        assert audit_result.response.verdict == "overturn"
        assert audit_result.response.note == "证据不足"
        assert audit_result.response.by == "human"

    asyncio.run(scenario())


def test_ai_proposal_is_type_checked_and_unavailable_ai_uses_by_none() -> None:
    from pokemon_agent.schemas.reviewer.interaction import ReviewProposal

    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        first = hub.open_ask(inject_request())
        assert hub.propose(1, ReviewProposal(answer=InjectAnswer(text="提议"))).ok
        result = await first
        assert result.response.text == "提议" and result.response.by == "agent"

        second = hub.open_ask(inject_request())
        assert hub.submit_default(2).ok
        result = await second
        assert result.response.text == "" and result.response.by == "none"
        assert result.response.answered is False

    asyncio.run(scenario())


def test_discuss_delegates_only_for_the_pending_question() -> None:
    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        calls: list[tuple[int, str]] = []

        def enqueue(seq: int, text: str) -> SubmitAck:
            calls.append((seq, text))
            return SubmitAck(ok=True, text="queued")

        hub.set_discuss_handler(enqueue)
        future = hub.open_ask(inject_request())

        assert hub.discuss(1, "check-repeat").ok
        assert calls == [(1, "check-repeat")]
        hub.cancel(1)
        await future
        assert not hub.discuss(1, "stale-note").ok

    asyncio.run(scenario())


def test_one_pending_question_is_a_precondition_and_history_is_bounded() -> None:
    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        for number in range(1, 56):
            future = hub.open_ask(inject_request())
            if number == 1:
                with pytest.raises(AssertionError, match="one review question"):
                    hub.open_ask(inject_request())
            assert hub.submit(number, InjectAnswer(), "human").ok
            await future
        assert len(hub.history(999)) == len(hub.activities()) == 50
        assert hub.history(999)[0].seq == 6 and not hub.history(0)

    asyncio.run(scenario())


def test_brain_frames_are_paged_from_the_pending_snapshot_and_stop_after_settlement() -> None:
    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        future = hub.open_ask(inject_request(frames=True))
        first = await hub.query(1, BrainFramesQuery())
        second = await hub.query(1, BrainFramesQuery(offset=2))
        empty = await hub.query(1, BrainFramesQuery(offset=99))
        assert len(first.images) == 2 and second.images == ["data:image/png;base64,Yw=="]
        assert "共 3 张" in first.text and "第 3–3 张" in second.text
        assert not empty.images and hub.current(1) is not None and not future.done()
        assert "data:" not in hub.context(1, "大脑输入").text
        assert "大脑输入" in hub.context(1).text and not hub.context(1, "missing").ok
        assert not hub.discuss(1, "hello").ok
        hub.cancel(1)
        await future
        assert not (await hub.query(1, BrainFramesQuery())).ok
        assert not hub.context(1).ok

    asyncio.run(scenario())


class BlockingTrace:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release query")
        return []


def test_a_blocked_read_does_not_block_submission_or_deliver_results_to_the_next_question() -> None:
    async def scenario() -> None:
        trace = BlockingTrace()
        hub = Hub(ViewReaders(trace, None))
        future = hub.open_ask(inject_request())
        query = asyncio.create_task(hub.query(1, TraceQuery()))
        try:
            assert await asyncio.to_thread(trace.started.wait, 3)
            assert hub.submit(1, InjectAnswer(), "human").ok
            await future
            next_future = hub.open_ask(inject_request())
        finally:
            trace.release.set()
        answer = await asyncio.wait_for(query, 3)
        assert not answer.ok and answer.text == "该问已了结"
        assert hub.current(2) is not None
        hub.cancel(2)
        await next_future

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: ReviewSeats(human=False, ai=False),
        lambda: AuditAnswer(verdict="overturn", note="  "),
        lambda: Settle(seq=1),
    ],
)
def test_external_invalid_interactions_are_validation_errors(constructor) -> None:
    with pytest.raises(ValidationError):
        constructor()


def test_notification_failure_does_not_leave_an_unanswerable_question() -> None:
    async def scenario() -> None:
        def fail(event) -> None:
            raise OSError("output failed")

        opening = Hub(ViewReaders(None, None), on_activity=fail)
        with pytest.raises(OSError):
            opening.open_ask(inject_request())
        assert opening.current() is None

        def fail_on_submit(event) -> None:
            if event.action == "submit":
                fail(event)

        hub = Hub(ViewReaders(None, None), on_activity=fail_on_submit)
        future = hub.open_ask(inject_request())
        with pytest.raises(OSError):
            hub.submit(1, InjectAnswer(text="accepted"), "human")
        result = await future
        assert result.response.text == "accepted" and hub.current() is None

    asyncio.run(scenario())
