"""注入终端行源跑完整进程内交互，EOF 和调用方取消都不会留下挂起问题。"""

import asyncio
import base64
import threading
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from _doubles.reviewer import audit_request, inject_request
from PIL import Image

from pokemon_agent.config import REVIEW_AI_COUNTDOWN_S
from pokemon_agent.reviewer.app import ReviewerApp
from pokemon_agent.reviewer.hub import Commands, Hub
from pokemon_agent.reviewer.seats.human import HumanSeat
from pokemon_agent.reviewer.view import ViewReaders
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.schemas.reviewer import ViewAnswer
from pokemon_agent.schemas.reviewer.interaction import (
    Ask,
    ReviewSeats,
)


async def lines(*values: str) -> AsyncIterator[str]:
    for value in values:
        yield value


def test_in_process_app_queries_then_answers_without_network(tmp_path: Path) -> None:
    async def scenario() -> None:
        output: list[str] = []
        human = HumanSeat(
            lines("ctx", "ask-ai check", "say 保留原话"), output.append, image_root=tmp_path
        )
        hub = Hub(ViewReaders(None, None), on_activity=human.activity)
        app = ReviewerApp(
            ReviewSeats(human=True, ai=False),
            hub=hub,
            commands=Commands(hub),
            human=human,
            countdown_s=REVIEW_AI_COUNTDOWN_S,
        )
        asking = asyncio.create_task(app.ask(inject_request()))
        await asyncio.sleep(0)

        await app.serve()
        result = await asking

        assert result.response.text == "保留原话" and result.response.by == "human"
        assert not hub.current() and len(hub.history()) == 1
        assert any("没有 AI 席" in text for text in output)
        assert sum("[1 inject] help / ctx" in text for text in output) >= 2
        assert all("data:" not in text for text in output)

    asyncio.run(scenario())


def test_eof_cancels_pending_and_closed_app_rejects_new_questions(tmp_path: Path) -> None:
    async def scenario() -> None:
        human = HumanSeat(lines(), lambda text: None, image_root=tmp_path)
        hub = Hub(ViewReaders(None, None))
        app = ReviewerApp(
            ReviewSeats(human=True, ai=False),
            hub=hub,
            commands=Commands(hub),
            human=human,
            countdown_s=REVIEW_AI_COUNTDOWN_S,
        )
        asking = asyncio.create_task(app.ask(inject_request()))
        await asyncio.sleep(0)

        await app.serve()

        assert (await asking).cancelled and hub.current() is None
        app.close()
        with pytest.raises(RuntimeError, match="已关闭"):
            await app.ask(inject_request())

    asyncio.run(scenario())


def test_cancelling_the_ask_cancels_hub_pending(tmp_path: Path) -> None:
    async def scenario() -> None:
        human = HumanSeat(lines(), lambda text: None, image_root=tmp_path)
        hub = Hub(ViewReaders(None, None))
        app = ReviewerApp(
            ReviewSeats(human=True, ai=False),
            hub=hub,
            commands=Commands(hub),
            human=human,
            countdown_s=REVIEW_AI_COUNTDOWN_S,
        )
        task = asyncio.create_task(app.ask(inject_request()))
        await asyncio.sleep(0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert hub.current() is None and hub.history()[0].settle.cancelled

    asyncio.run(scenario())


def test_terminal_saves_real_pngs_without_printing_image_encoding_or_overwriting(
    tmp_path: Path,
) -> None:
    output: list[str] = []
    seat = HumanSeat(lines(), output.append, image_root=tmp_path)
    png = BytesIO()
    Image.new("RGB", (3, 2), "red").save(png, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
    answer = ViewAnswer(ok=True, text="第 1 步 before", images=[uri])

    seat.show_result(1, answer)
    seat.show_result(1, answer)

    paths = sorted(tmp_path.glob("*.png"))
    assert len(paths) == 2 and paths[0] != paths[1]
    for path in paths:
        with Image.open(path) as image:
            assert image.size == (3, 2)
    assert all("data:" not in text for text in output)
    assert sum("3×2" in text for text in output) == 2
    assert "before" in output[0]


def test_bad_image_reports_failure_without_crashing_the_terminal(tmp_path: Path) -> None:
    output: list[str] = []
    seat = HumanSeat(lines(), output.append, image_root=tmp_path)

    seat.show_result(1, ViewAnswer(ok=True, text="frame", images=["data:image/png;base64,YQ=="]))
    seat.show_ask(Ask(seq=1, request=inject_request(frames=True)))

    assert any("画面保存失败" in text for text in output)
    assert not list(tmp_path.glob("*.png")) and all("data:" not in text for text in output)


def test_proposal_controls_explain_inject_and_audit_actions(tmp_path: Path) -> None:
    output: list[str] = []
    seat = HumanSeat(lines(), output.append, image_root=tmp_path)

    seat.show_proposal(Ask(seq=1, request=inject_request()), "建议", 30)
    seat.show_proposal(Ask(seq=2, request=audit_request()), "认账", 30)

    assert output[1] == (
        "30 秒内：say <意见> 提交你的意见；ask-ai <要求> 让 AI 重拟；"
        "ok 提交空意见。倒计时结束自动采用 AI 提案。"
    )
    assert output[3] == (
        "30 秒内：ok 接受当前判定；overturn <理由> 推翻并继续；"
        "ask-ai <要求> 让 AI 重拟。倒计时结束自动采用 AI 判定。"
    )


class SlowTrace:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("test query blocked")
        return []


def test_terminal_keeps_accepting_an_answer_while_a_query_is_blocked(tmp_path: Path) -> None:
    async def scenario() -> None:
        trace = SlowTrace()

        async def inputs() -> AsyncIterator[str]:
            yield "trace"
            assert await asyncio.to_thread(trace.started.wait, 2)
            yield "say 先提交"

        seat = HumanSeat(inputs(), lambda text: None, image_root=tmp_path)
        hub = Hub(ViewReaders(trace, None))
        app = ReviewerApp(
            ReviewSeats(human=True, ai=False),
            hub=hub,
            commands=Commands(hub),
            human=seat,
            countdown_s=REVIEW_AI_COUNTDOWN_S,
        )
        asking = asyncio.create_task(app.ask(inject_request()))
        await asyncio.sleep(0)

        try:
            await asyncio.wait_for(app.serve(), 3)
            assert (await asking).response.text == "先提交"
        finally:
            trace.release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "seats", [ReviewSeats(human=True, ai=True), ReviewSeats(human=False, ai=True)]
)
def test_app_requires_each_enabled_seat_to_be_injected(tmp_path: Path, seats: ReviewSeats) -> None:
    hub = Hub(ViewReaders(None, None))
    human = HumanSeat(lines(), lambda text: None, image_root=tmp_path)

    with pytest.raises(ValueError, match="必须且只能注入"):
        ReviewerApp(
            seats,
            hub=hub,
            commands=Commands(hub),
            human=human,
            countdown_s=REVIEW_AI_COUNTDOWN_S,
        )


def test_ai_only_mode_submits_structured_proposal_without_terminal() -> None:
    from pokemon_agent.schemas.reviewer.interaction import InjectAnswer, ReviewProposal

    class Ai:
        async def run_turn(self, ask, human_note="") -> ReviewProposal:
            return ReviewProposal(answer=InjectAnswer(text="AI 建议"))

    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        app = ReviewerApp(
            ReviewSeats(human=False, ai=True),
            hub=hub,
            commands=Commands(hub),
            human=None,
            ai=Ai(),
            countdown_s=REVIEW_AI_COUNTDOWN_S,
        )

        result = await asyncio.wait_for(app.ask(inject_request()), timeout=1)

        assert result.response.text == "AI 建议" and result.response.by == "agent"
        assert not hub.current()

    asyncio.run(scenario())


def test_ai_only_failure_uses_unanswered_default() -> None:
    class Ai:
        async def run_turn(self, ask, human_note=""):
            return None

    async def scenario() -> None:
        hub = Hub(ViewReaders(None, None))
        app = ReviewerApp(
            ReviewSeats(human=False, ai=True),
            hub=hub,
            commands=Commands(hub),
            human=None,
            ai=Ai(),
            countdown_s=REVIEW_AI_COUNTDOWN_S,
        )

        result = await asyncio.wait_for(app.ask(inject_request()), timeout=1)

        assert result.response.text == ""
        assert result.response.answered is False and result.response.by == "none"

    asyncio.run(scenario())


def test_human_answer_takes_over_ai_proposal_during_countdown(tmp_path: Path) -> None:
    from pokemon_agent.schemas.reviewer.interaction import InjectAnswer, ReviewProposal

    async def scenario() -> None:
        proposal_shown = asyncio.Event()
        output: list[str] = []

        def write(text: str) -> None:
            output.append(text)
            if text.startswith("[AI "):
                proposal_shown.set()

        async def inputs() -> AsyncIterator[str]:
            await proposal_shown.wait()
            yield "ok"
            await asyncio.sleep(0.02)

        class Ai:
            async def run_turn(self, ask, human_note="") -> ReviewProposal:
                return ReviewProposal(
                    answer=InjectAnswer(text="建议按当前方案继续。\n依据：角色已在草丛内。")
                )

        human = HumanSeat(inputs(), write, image_root=tmp_path)
        hub = Hub(ViewReaders(None, None))
        app = ReviewerApp(
            ReviewSeats(human=True, ai=True),
            hub=hub,
            commands=Commands(hub),
            human=human,
            ai=Ai(),
            countdown_s=1,
        )
        asking = asyncio.create_task(app.ask(inject_request()))
        await asyncio.sleep(0)

        await asyncio.wait_for(app.serve(), timeout=1)
        result = await asyncio.wait_for(asking, timeout=1)

        assert result.response.text == "" and result.response.by == "human"
        proposal_line = next(line for line in output if line.startswith("[AI 提案"))
        assert proposal_line == "[AI 提案 1] 建议按当前方案继续。\n依据：角色已在草丛内。"
        assert all('"answer"' not in line and "\\u" not in line for line in output)

    asyncio.run(scenario())
