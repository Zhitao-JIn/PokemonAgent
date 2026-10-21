"""真实 WS 回环与进程内应用共用的测试装配，不连接模拟器或模型。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from _harness_fixtures.app_config import DEFAULT_APP_CONFIG

from pokemon_agent.reviewer.app import ReviewerApp
from pokemon_agent.reviewer.hub import Commands, Hub
from pokemon_agent.reviewer.link.server import ReviewLinkServer
from pokemon_agent.reviewer.seats.human import HumanSeat
from pokemon_agent.reviewer.view import ViewReaders
from pokemon_agent.schemas.reviewer.interaction import Activity, ReviewSeats


@dataclass
class LinkedReviewer:
    url: str
    hub: Hub
    opened: asyncio.Queue[int]
    app: ReviewerApp
    service: ReviewLinkServer
    output: list[str]


async def _unused_lines() -> AsyncIterator[str]:
    for line in ():
        yield line


@asynccontextmanager
async def reviewer_server(root: Path) -> AsyncIterator[LinkedReviewer]:
    """搭配真实 app/hub/服务启动临时端口，测试显式驱动人的类型化答复。"""
    opened: asyncio.Queue[int] = asyncio.Queue()
    output: list[str] = []

    def activity(event: Activity) -> None:
        if event.action == "open":
            opened.put_nowait(event.seq)

    seat = HumanSeat(_unused_lines(), output.append, image_root=root)
    hub = Hub(ViewReaders(None, None), on_activity=activity)
    app = ReviewerApp(
        ReviewSeats(human=True, ai=False),
        hub=hub,
        commands=Commands(hub),
        human=seat,
        countdown_s=DEFAULT_APP_CONFIG.review.ai_countdown_s,
    )
    service = ReviewLinkServer(app, mode="human")
    async with await service.serve("127.0.0.1", 0) as listener:
        port = listener.sockets[0].getsockname()[1]
        try:
            yield LinkedReviewer(f"ws://127.0.0.1:{port}", hub, opened, app, service, output)
        finally:
            await service.shutdown()
            app.close()
