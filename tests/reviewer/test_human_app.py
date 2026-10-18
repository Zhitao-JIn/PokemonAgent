"""注入终端行源跑完整进程内交互，EOF 和调用方取消都不会留下挂起问题。"""

import asyncio
import base64
import threading
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from _doubles.reviewer import inject_request
from PIL import Image

from pokemon_agent.reviewer.app import ReviewerApp
from pokemon_agent.reviewer.hub import Commands, Hub
from pokemon_agent.reviewer.seats.human import HumanSeat
from pokemon_agent.reviewer.view import ViewReaders
from pokemon_agent.schemas.harness import TraceEvent
from pokemon_agent.schemas.reviewer import ViewAnswer
from pokemon_agent.schemas.reviewer.interaction import Ask, ReviewSeats


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
            ReviewSeats(human=True, ai=False), hub=hub, commands=Commands(hub), human=human
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
            ReviewSeats(human=True, ai=False), hub=hub, commands=Commands(hub), human=human
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
            ReviewSeats(human=True, ai=False), hub=hub, commands=Commands(hub), human=human
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
            ReviewSeats(human=True, ai=False), hub=hub, commands=Commands(hub), human=seat
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
def test_r6a_rejects_unimplemented_ai_modes(tmp_path: Path, seats: ReviewSeats) -> None:
    hub = Hub(ViewReaders(None, None))
    human = HumanSeat(lines(), lambda text: None, image_root=tmp_path)

    with pytest.raises(ValueError, match="仅支持 human"):
        ReviewerApp(seats, hub=hub, commands=Commands(hub), human=human)
