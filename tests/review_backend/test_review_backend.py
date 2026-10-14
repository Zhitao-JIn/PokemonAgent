"""后端协议的用法示范：**一个 run 连 `/harness` 发问、网页连 `/ui` 答，回话怎么走**。

每个用例在本进程的事件循环里起一台真后端（端口由系统挑），两端都是真的 WebSocket 客户端：
一端扮 `WebReviewer`（发跳 A 请求），一端扮网页（收推送、发答案）。
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as _connect
from websockets.exceptions import ConnectionClosed

from pokemon_agent.harness.web_reviewer import WebReviewer
from pokemon_agent.review_backend import ReviewBackend
from pokemon_agent.schemas.harness import (
    FromHarnessToReviewBackendAuditReq,
    FromHarnessToReviewBackendAuditResp,
    FromHarnessToReviewBackendInjectReq,
    FromHarnessToReviewBackendInjectResp,
    FromHarnessToReviewerInjectReq,
)

Scenario = Callable[[str], Awaitable[None]]


def connect(url: str, **kwargs: object) -> ClientConnection:
    """连本机后端：显式不走代理（本机开着 HTTP(S)_PROXY 时，回环地址也可能被送去代理）。"""
    return _connect(url, proxy=None, **kwargs)  # type: ignore[arg-type]


def _run(scenario: Scenario) -> None:
    """起一台后端，把 `ws://127.0.0.1:<port>` 交给场景，跑完关掉。"""

    async def main() -> None:
        async with ReviewBackend().serve("127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            await asyncio.wait_for(scenario(f"127.0.0.1:{port}"), timeout=10)

    asyncio.run(main())


def _inject(timeout_s: float = 5) -> str:
    return FromHarnessToReviewBackendInjectReq(
        run_id="r1",
        prompt="拆得对吗",
        form_kind="Decomposition",
        form_text="{...}",
        timeout_s=timeout_s,
    ).model_dump_json()


def _audit(timeout_s: float = 5) -> str:
    return FromHarnessToReviewBackendAuditReq(
        run_id="r1",
        episode_id="r1-ep1",
        prompt="审模型裁决",
        form_kind="JudgeVerdict",
        outcome_text="模型说 已达成",
        events=["12:00:00 · judge_call · review_and_judge · 3 · {...}"],
        timeout_s=timeout_s,
    ).model_dump_json()


async def _next(conn: ClientConnection, msg: str) -> dict:
    """读到下一封标签为 `msg` 的消息。"""
    while True:
        data = json.loads(await conn.recv())
        if data["msg"] == msg:
            return data


def test_the_page_answers_an_inject_and_the_run_gets_it() -> None:
    """插话：run 发问 → 网页收到这一问 → 网页答 → 回执 ok → run 收到人的话、`answered=True`。"""

    async def scenario(addr: str) -> None:
        async with connect(f"ws://{addr}/ui") as page, connect(f"ws://{addr}/harness") as run:
            await run.send(_inject())
            ask = await _next(page, "ask")
            assert (ask["kind"], ask["prompt"], ask["body"]) == ("inject", "拆得对吗", "{...}")
            await page.send(json.dumps({"msg": "answer", "seq": ask["seq"], "text": "先进门"}))
            assert (await _next(page, "answer_ack"))["ok"] is True
            resp = FromHarnessToReviewBackendInjectResp.model_validate_json(await run.recv())
            assert (resp.seq, resp.text, resp.answered) == (ask["seq"], "先进门", True)
            assert (await _next(page, "settle"))["by"] == "human"

    _run(scenario)


def test_an_audit_empty_answer_is_settled_as_timeout() -> None:
    """审：前端发空答案（没人实质作答）→ settle.by == 'timeout'、认账、answered=False。

    A3 起后端不再自管超时（timeout=None，计时交前端 / agent）；"超时"现在由前端的空答案触发
    （`answer_by` 判空框为 timeout）。
    """

    async def scenario(addr: str) -> None:
        async with connect(f"ws://{addr}/ui") as page, connect(f"ws://{addr}/harness") as run:
            await run.send(_audit())
            ask = await _next(page, "ask")
            assert ask["events"] and ask["episode_id"] == "r1-ep1"
            # 前端发显式超时答案（by="timeout"，没填 verdict / note）——等价于"超时，按默认处理"。
            await page.send(json.dumps({"msg": "answer", "seq": ask["seq"], "by": "timeout"}))
            resp = FromHarnessToReviewBackendAuditResp.model_validate_json(await run.recv())
            assert (resp.verdict.value, resp.answered) == ("accept", False)
            assert (await _next(page, "settle"))["by"] == "timeout"

    _run(scenario)


def test_first_answer_wins_and_a_mismatched_answer_is_refused() -> None:
    """两个标签页：答案与问不配 → 不采纳；先答的采纳，后到的回「已被别处答了」或「已了结」。"""

    async def scenario(addr: str) -> None:
        async with (
            connect(f"ws://{addr}/ui") as tab1,
            connect(f"ws://{addr}/ui") as tab2,
            connect(f"ws://{addr}/harness") as run,
        ):
            await run.send(_audit())
            seq = (await _next(tab1, "ask"))["seq"]
            await _next(tab2, "ask")
            await tab1.send(json.dumps({"msg": "answer", "seq": seq, "text": "文字答审"}))
            assert (await _next(tab1, "answer_ack"))["reason"] == "答案与问不配"
            await tab1.send(json.dumps({"msg": "answer", "seq": seq, "verdict": "overturn"}))
            await tab2.send(json.dumps({"msg": "answer", "seq": seq, "verdict": "accept"}))
            assert (await _next(tab1, "answer_ack"))["ok"] is True
            assert (await _next(tab2, "answer_ack"))["ok"] is False
            resp = FromHarnessToReviewBackendAuditResp.model_validate_json(await run.recv())
            assert resp.verdict.value == "overturn"

    _run(scenario)


def test_a_second_run_is_refused() -> None:
    """同一时刻只服务一个 run：第二条 `/harness` 连接被以 1008 关掉。"""

    async def scenario(addr: str) -> None:
        async with connect(f"ws://{addr}/harness"), connect(f"ws://{addr}/harness") as second:
            with pytest.raises(ConnectionClosed) as caught:
                await second.recv()
            assert caught.value.rcvd is not None and caught.value.rcvd.code == 1008

    _run(scenario)


def test_a_reconnecting_page_gets_the_history_and_the_pending_ask() -> None:
    """网页重连：先补发历史（问 + 了结），再补发当前待答的那一问。

    A3 起后端不再自管超时，第一问由网页（UI）显式答掉后进历史；第二问保持 pending 等重连补收。
    """

    async def scenario(addr: str) -> None:
        async with connect(f"ws://{addr}/harness") as run:
            # 先答掉第一问（插话），让它进历史。
            async with connect(f"ws://{addr}/ui") as page0:
                await run.send(_inject())
                ask0 = await _next(page0, "ask")
                await page0.send(json.dumps({"msg": "answer", "seq": ask0["seq"], "text": "x"}))
                assert (await _next(page0, "settle"))["by"] == "human"
            # 第二问（审）保持 pending，等重连的网页补收。
            await run.send(_audit())
            await asyncio.sleep(0.1)
            async with connect(f"ws://{addr}/ui") as page:
                kinds = [json.loads(await page.recv())["msg"] for _ in range(3)]
                assert kinds == ["ask", "settle", "ask"]

    _run(scenario)


def test_the_pending_ask_is_voided_when_the_run_goes_away() -> None:
    """run 在等人时断开 → 网页收到「run 断开，作废」的了结。"""

    async def scenario(addr: str) -> None:
        async with connect(f"ws://{addr}/ui") as page:
            async with connect(f"ws://{addr}/harness") as run:
                await run.send(_inject())
                await _next(page, "ask")
            assert (await _next(page, "settle"))["by"] == "harness_gone"

    _run(scenario)


def test_the_page_and_health_are_plain_http() -> None:
    """`GET /` 是单页、`GET /health` 说有没有 run 连着。"""

    async def scenario(addr: str) -> None:
        def get(path: str) -> tuple[str, str]:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://{addr}{path}", timeout=5) as resp:
                return resp.headers["Content-Type"], resp.read().decode("utf-8")

        loop = asyncio.get_running_loop()
        page_type, page = await loop.run_in_executor(None, get, "/")
        assert page_type.startswith("text/html") and "人在环" in page
        # 事件里的 `frame` 已是完整 data URI（0915 唯一格式）——页面直接上 src，
        # 不得再拼一次 `data:image/png;base64,` 前缀（拼了就是坏图）。
        assert "item.content.frame" in page and "base64,${" not in page
        async with connect(f"ws://{addr}/harness"):
            _, health = await loop.run_in_executor(None, get, "/health")
            assert json.loads(health)["harness_connected"] is True

    _run(scenario)


def test_an_oversized_feed_event_still_reaches_the_page() -> None:
    """/feed 不设收包上限：带整批帧的账（>1 MiB）照样转播，后端不掐 run 的连接。

    网页（浏览器）收大消息没有上限；本测试扮网页的客户端要显式 `max_size=None`
    ——websockets 客户端跟服务端一样缺省 1 MiB。
    """

    async def scenario(addr: str) -> None:
        from pokemon_agent.schemas.harness import (
            FromHarnessToReviewBackendFeedReq,
            TraceEvent,
        )

        frame = "data:image/png;base64," + "A" * (2 * 1024 * 1024)
        event = TraceEvent(
            uuid="u1",
            seq=1,
            kind="sense_frame",
            type="view",
            started_at=1.0,
            ended_at=1.0,
            meta=json.dumps({"source": "s", "episode_id": "e", "task_id": "t", "step": 1}),
            content=json.dumps({"frame": frame}),
        )
        async with connect(f"ws://{addr}/ui", max_size=None) as page:
            async with connect(f"ws://{addr}/feed") as run:
                await run.send(
                    FromHarnessToReviewBackendFeedReq(run_id="r1", event=event).model_dump_json()
                )
            got = await _next(page, "feed")
            assert json.loads(got["event"]["content"])["frame"] == frame

    _run(scenario)


def test_web_reviewer_round_trip_through_the_backend() -> None:
    """`WebReviewer` 在 run 这一端：同步地问，网页那一端答，回到进程内的 Resp。"""

    async def scenario(addr: str) -> None:
        loop = asyncio.get_running_loop()
        async with connect(f"ws://{addr}/ui") as page:
            reviewer = await loop.run_in_executor(None, lambda: WebReviewer("r1", f"ws://{addr}"))
            req = FromHarnessToReviewerInjectReq(
                prompt="拆得对吗", form={"tasks": []}, form_kind="x"
            )
            asked = loop.run_in_executor(None, reviewer.inject, req)
            ask = await _next(page, "ask")
            await page.send(json.dumps({"msg": "answer", "seq": ask["seq"], "text": "先进门"}))
            resp = await asked
            assert (resp.text, resp.answered) == ("先进门", True)
            await loop.run_in_executor(None, reviewer.close)

    _run(scenario)


def test_web_reviewer_refuses_to_start_without_a_backend() -> None:
    """后端没起：构造时就抛 `OSError`，不等一局跑完才发现没人能接。"""
    with pytest.raises(OSError, match="连不上人在环后端"):
        WebReviewer("r1", "ws://127.0.0.1:1")


def test_web_reviewer_degrades_when_the_backend_goes_away() -> None:
    """后端中途没了：这一问与之后都按默认值，`answered=False`，run 不中断。"""

    holder: list[WebReviewer] = []

    async def keep(addr: str) -> None:
        loop = asyncio.get_running_loop()
        holder.append(await loop.run_in_executor(None, lambda: WebReviewer("r1", f"ws://{addr}")))

    _run(keep)
    req = FromHarnessToReviewerInjectReq(prompt="p", form="f", form_kind="x")
    first, second = holder[0].inject(req), holder[0].inject(req)
    assert (first.answered, first.text, second.answered) == (False, "", False)


def test_live_trace_reaches_the_page_as_it_is_written(tmp_path: Path) -> None:
    """每落一笔账，网页实时收到同一条事件（带画面的也一样）；重连的网页先拿到最近的那些。"""
    from pokemon_agent.direct.trace import TraceTool
    from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

    async def scenario(addr: str) -> None:
        loop = asyncio.get_running_loop()
        async with connect(f"ws://{addr}/ui") as page:
            trace = TraceTool.build(run_id="r1", trace_root=tmp_path, live_feed_url=f"ws://{addr}")
            req = FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ADVANCE_STEP,
                meta={"source": "s", "episode_id": "e", "task_id": "t", "step": 1},
                next_step=2,
            )
            await loop.run_in_executor(None, trace.append, req)
            got = await _next(page, "feed")
            assert got["event"]["kind"] == "advance_step"
            assert json.loads(got["event"]["meta"])["run_id"] == "r1"
        async with connect(f"ws://{addr}/ui") as again:
            assert (await _next(again, "feed"))["event"]["kind"] == "advance_step"

    _run(scenario)


def test_live_trace_without_a_backend_changes_nothing_on_disk(tmp_path: Path) -> None:
    """后端没起：照样落盘、不抛、不拖慢——推送那一路静静地丢掉。"""
    from pokemon_agent.direct.trace import TraceTool
    from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

    trace = TraceTool.build(run_id="r1", trace_root=tmp_path, live_feed_url="ws://127.0.0.1:1")
    started = time.monotonic()
    for step in range(50):
        trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ADVANCE_STEP,
                meta={"source": "s", "episode_id": "e", "task_id": "t", "step": step},
                next_step=step + 1,
            )
        )
    assert time.monotonic() - started < 5
    assert len(trace.read_events({"run_id": "r1"})) == 50
