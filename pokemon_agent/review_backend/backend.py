"""`ReviewBackend`：人在环的常驻后端——一台 WebSocket 服务器，源程序与网页都连它。

路径（`docs/web_reviewer/spec.md` §5）：
- `GET /` 单页、`GET /health` 状态 JSON——握手前由 `process_request` 直接回，不升级；
- `/harness`：一个 run 一条连接，发插话 / 审请求（跳 A），等回话；同一时刻只许一条；
- `/feed`：run 的实时 trace（单向，无回话），原样转播给网页；
- `/ui`：网页；连上先补发最近的实时 trace、历史与当前待答的一问，
  此后收推送、发答案、收回执（跳 B）。

后端不懂游戏：只搬源程序渲染好的文本。状态只在内存（编号、待答、最近若干问的历史），
定案账在 trace 里。单个 asyncio 事件循环，状态不需要锁。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewBackendAuditReq,
    FromHarnessToReviewBackendAuditResp,
    FromHarnessToReviewBackendFeedReq,
    FromHarnessToReviewBackendInjectReq,
    FromHarnessToReviewBackendInjectResp,
)
from pokemon_agent.schemas.review_backend import (
    FromFrontendToReviewBackendAnswerReq,
    FromFrontendToReviewBackendAnswerResp,
    FromReviewBackendToFrontendAskReq,
    FromReviewBackendToFrontendFeedReq,
    FromReviewBackendToFrontendSettleReq,
)

from .page import PAGE_HTML

HISTORY_LIMIT = 50
"""网页重连时补发的历史条数（一问一条）。"""

FEED_LIMIT = 300
"""网页重连时补发的实时 trace 条数。"""

POLICY_VIOLATION = 1008
"""拒绝连接时的 WebSocket 关闭码（RFC 6455：违反策略）。"""

HarnessReq = FromHarnessToReviewBackendInjectReq | FromHarnessToReviewBackendAuditReq
HarnessResp = FromHarnessToReviewBackendInjectResp | FromHarnessToReviewBackendAuditResp


@dataclass
class _Pending:
    """当前待答的一问：推给网页的那封，与等网页答案的 future。"""

    ask: FromReviewBackendToFrontendAskReq
    answer: asyncio.Future[FromFrontendToReviewBackendAnswerReq]


class ReviewBackend:
    """后端的全部状态与三条路由。用法：`async with backend.serve(host, port) as server: ...`。"""

    def __init__(self) -> None:
        self._seq = 0
        self._pending: _Pending | None = None
        self._history: deque[
            tuple[FromReviewBackendToFrontendAskReq, FromReviewBackendToFrontendSettleReq]
        ] = deque(maxlen=HISTORY_LIMIT)
        self._feed: deque[str] = deque(maxlen=FEED_LIMIT)
        self._ui: set[ServerConnection] = set()
        self._harness: ServerConnection | None = None

    def serve(self, host: str, port: int) -> serve:
        """起服务（`async with` 用）；`port=0` 由系统挑。端口被占时进入即抛 `OSError`。

        `max_size=None`：不设收包上限。websockets 缺省 1 MiB，而 `/feed` 转播的
        `choose_call`/`judge_call` 等账的 `payload.images` 带着整批 data URI 帧，
        单条轻松超限——超限后端就以 1009 掐断 run 的推送连接，`LiveFeedTrace`
        的重连退避期（5s）里队列事件逐条丢弃，实时画面成片缺失。
        """
        return serve(self._route, host, port, process_request=self._process_request, max_size=None)

    def health(self) -> dict[str, object]:
        """`GET /health` 的内容：待答的是第几问、有没有 run 连着。"""
        return {
            "ok": True,
            "pending_seq": self._pending.ask.seq if self._pending else None,
            "harness_connected": self._harness is not None,
        }

    # ---- 握手前：普通 HTTP ----

    def _process_request(self, conn: ServerConnection, request: Request) -> Response | None:
        """`/` 与 `/health` 直接回；两条 WebSocket 路径放行去握手；其余 404。"""
        path = request.path.split("?", 1)[0]
        if path in ("/harness", "/feed", "/ui"):
            return None
        if path == "/":
            return _respond(conn, PAGE_HTML, "text/html; charset=utf-8")
        if path == "/health":
            return _respond(conn, json.dumps(self.health()), "application/json")
        return conn.respond(HTTPStatus.NOT_FOUND, "not found\n")

    async def _route(self, conn: ServerConnection) -> None:
        """按握手路径分到三条连接的处理。"""
        path = conn.request.path.split("?", 1)[0] if conn.request is not None else ""
        if path == "/harness":
            await self._serve_harness(conn)
        elif path == "/feed":
            await self._serve_feed(conn)
        else:
            await self._serve_ui(conn)

    # ---- /harness：源程序 ----

    async def _serve_harness(self, conn: ServerConnection) -> None:
        """一个 run 的整条连接：逐问转给网页、等答案、回话。第二个 run 连进来直接拒。"""
        if self._harness is not None:
            _say("又有一个 run 想连进来，已拒绝（同一时刻只服务一个 run）")
            await conn.close(POLICY_VIOLATION, "another run is connected")
            return
        self._harness = conn
        _say("run 连上了")
        try:
            async for raw in conn:
                req = _parse_harness(raw)
                if req is None:
                    await conn.close(POLICY_VIOLATION, "bad request")
                    return
                resp = await self._ask(conn, req)
                if resp is not None:
                    await conn.send(resp.model_dump_json())
        except ConnectionClosed:
            pass
        finally:
            self._harness = None
            _say("run 断开了")

    async def _ask(self, conn: ServerConnection, req: HarnessReq) -> HarnessResp | None:
        """推一问、等人答 / 超时 / run 断开，了结并记进历史；run 断开时返回 None。"""
        # 步骤 1：编号、挂起、推给网页。
        self._seq += 1
        ask = _to_ask(self._seq, req)
        answer: asyncio.Future[FromFrontendToReviewBackendAnswerReq] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending = _Pending(ask, answer)
        broadcast(self._ui, ask.model_dump_json())
        _say(f"第 {ask.seq} 问（{ask.kind}）：{ask.prompt}")

        # 步骤 2：等三件事里先到的那件。
        gone = asyncio.ensure_future(conn.wait_closed())
        try:
            done, _ = await asyncio.wait(
                {answer, gone}, timeout=req.timeout_s, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            gone.cancel()
            self._pending = None
        if answer in done:
            by = "human"
        elif gone in done:
            by = "harness_gone"
        else:
            by = "timeout"

        # 步骤 3：了结、广播、记历史。
        settle = _settle(ask, answer.result() if by == "human" else None, by)
        self._history.append((ask, settle))
        broadcast(self._ui, settle.model_dump_json())
        _say(f"第 {ask.seq} 问了结：{by}")
        if by == "harness_gone":
            return None
        return _to_resp(settle, answered=by == "human")

    # ---- /feed：实时 trace ----

    async def _serve_feed(self, conn: ServerConnection) -> None:
        """收 run 推来的每条事件，记进缓冲并转播；看不懂的丢弃。"""
        try:
            async for raw in conn:
                try:
                    item = FromHarnessToReviewBackendFeedReq.model_validate_json(raw)
                except ValidationError:
                    continue
                message = FromReviewBackendToFrontendFeedReq(
                    run_id=item.run_id, event=item.event
                ).model_dump_json()
                self._feed.append(message)
                broadcast(self._ui, message)
        except ConnectionClosed:
            pass

    # ---- /ui：网页 ----

    async def _serve_ui(self, conn: ServerConnection) -> None:
        """一个网页的整条连接：补发历史与待答，此后收答案、回回执。"""
        self._ui.add(conn)
        try:
            for message in list(self._feed):
                await conn.send(message)
            for ask, settle in self._history:
                await conn.send(ask.model_dump_json())
                await conn.send(settle.model_dump_json())
            if self._pending is not None:
                await conn.send(self._pending.ask.model_dump_json())
            async for raw in conn:
                resp = self._answer(raw)
                if resp is not None:
                    await conn.send(resp.model_dump_json())
        except ConnectionClosed:
            pass
        finally:
            self._ui.discard(conn)

    def _answer(self, raw: str | bytes) -> FromFrontendToReviewBackendAnswerResp | None:
        """收一份答案：先答先得；已了结、编号不对、与问不配都回 `ok=False`。看不懂的消息丢弃。"""
        try:
            req = FromFrontendToReviewBackendAnswerReq.model_validate_json(raw)
        except ValidationError as exc:
            _say(f"网页发来看不懂的消息，丢弃：{exc.errors()[:1]}")
            return None
        pending = self._pending
        if pending is None or pending.ask.seq != req.seq:
            return _ack(req.seq, "这一问已了结或不存在")
        if pending.answer.done():
            return _ack(req.seq, "已被别处答了")
        if (pending.ask.kind == "inject" and req.text is None) or (
            pending.ask.kind == "audit" and req.verdict is None
        ):
            return _ack(req.seq, "答案与问不配")
        pending.answer.set_result(req)
        return _ack(req.seq, "")


def _parse_harness(raw: str | bytes) -> HarnessReq | None:
    """按 `msg` 标签解一封跳 A 请求；看不懂返回 None（并打一行日志）。"""
    try:
        data = json.loads(raw)
        if data.get("msg") == "inject":
            return FromHarnessToReviewBackendInjectReq.model_validate(data)
        if data.get("msg") == "audit":
            return FromHarnessToReviewBackendAuditReq.model_validate(data)
        _say(f"run 发来未知消息：{data.get('msg')!r}")
    except (ValueError, AttributeError, ValidationError) as exc:
        _say(f"run 发来看不懂的请求：{exc}")
    return None


def _to_ask(seq: int, req: HarnessReq) -> FromReviewBackendToFrontendAskReq:
    """把跳 A 请求摊平成推给网页的一问。"""
    deadline = time.time() + req.timeout_s
    if isinstance(req, FromHarnessToReviewBackendInjectReq):
        return FromReviewBackendToFrontendAskReq(
            seq=seq,
            run_id=req.run_id,
            kind="inject",
            prompt=req.prompt,
            form_kind=req.form_kind,
            body=req.form_text,
            deadline=deadline,
        )
    return FromReviewBackendToFrontendAskReq(
        seq=seq,
        run_id=req.run_id,
        kind="audit",
        prompt=req.prompt,
        form_kind=req.form_kind,
        body=req.outcome_text,
        events=req.events,
        episode_id=req.episode_id,
        task_id=req.task_id,
        deadline=deadline,
    )


def _settle(
    ask: FromReviewBackendToFrontendAskReq,
    answer: FromFrontendToReviewBackendAnswerReq | None,
    by: str,
) -> FromReviewBackendToFrontendSettleReq:
    """一问的结局：人答了取人的答案；否则插话空串、审认账。"""
    if ask.kind == "inject":
        text = (answer.text or "") if answer is not None else ""
        return FromReviewBackendToFrontendSettleReq(seq=ask.seq, by=by, text=text)
    if answer is not None and answer.verdict is not None:
        return FromReviewBackendToFrontendSettleReq(
            seq=ask.seq, by=by, verdict=answer.verdict, note=answer.note
        )
    return FromReviewBackendToFrontendSettleReq(seq=ask.seq, by=by, verdict=AuditVerdict.ACCEPT)


def _to_resp(settle: FromReviewBackendToFrontendSettleReq, *, answered: bool) -> HarnessResp:
    """了结的一问翻成回给源程序的跳 A 回话。"""
    if settle.verdict is None:
        return FromHarnessToReviewBackendInjectResp(
            seq=settle.seq, text=settle.text, answered=answered
        )
    return FromHarnessToReviewBackendAuditResp(
        seq=settle.seq, verdict=settle.verdict, note=settle.note, answered=answered
    )


def _ack(seq: int, reason: str) -> FromFrontendToReviewBackendAnswerResp:
    """回执：`reason` 为空即采纳。"""
    return FromFrontendToReviewBackendAnswerResp(seq=seq, ok=not reason, reason=reason)


def _respond(conn: ServerConnection, body: str, content_type: str) -> Response:
    """握手前回一个 200 的普通 HTTP 响应。"""
    response = conn.respond(HTTPStatus.OK, body)
    del response.headers["Content-Type"]
    response.headers["Content-Type"] = content_type
    return response


def _say(line: str) -> None:
    """后端动态一行一条打到 stdout（带 flush，重定向进文件时也实时可见）。"""
    print(f"[review-backend] {line}", flush=True)


__all__ = ["FEED_LIMIT", "HISTORY_LIMIT", "ReviewBackend"]
