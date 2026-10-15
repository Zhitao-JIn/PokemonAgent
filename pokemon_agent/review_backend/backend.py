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

from pokemon_agent.schemas.agent_reviewer.communication import ChatTurn, ProposalMsg
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
    FromFrontendToReviewBackendDiscussReq,
    FromReviewBackendToFrontendAskReq,
    FromReviewBackendToFrontendFeedReq,
    FromReviewBackendToFrontendProposalReq,
    FromReviewBackendToFrontendSettleReq,
)

from .agent_client import AgentClient
from .page import PAGE_HTML

HISTORY_LIMIT = 50
"""网页重连时补发的历史条数（一问一条）。"""

FEED_LIMIT = 300
"""网页重连时补发的实时 trace 条数。"""

AI_COUNTDOWN = 30.0
"""AI 模式默认倒计时（秒）：前端从首个 proposal 到达才开始计，归零自动提交。"""

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

    def __init__(self, agent_client: AgentClient | None = None) -> None:
        self._seq = 0
        self._pending: _Pending | None = None
        self._history: deque[
            tuple[FromReviewBackendToFrontendAskReq, FromReviewBackendToFrontendSettleReq]
        ] = deque(maxlen=HISTORY_LIMIT)
        self._feed: deque[str] = deque(maxlen=FEED_LIMIT)
        self._ui: set[ServerConnection] = set()
        self._harness: ServerConnection | None = None
        self._agent: AgentClient | None = agent_client
        self._rounds: dict[int, int] = {}

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

    async def start_agent(self) -> None:
        """连 agent 进程（跳 C）；连不上降级为无 agent，不崩。须在有事件循环里调。"""
        if self._agent is None:
            return
        ok = await self._agent.connect(self._receive_proposal)
        if not ok:
            _say("[agent] 未连上，降级为无 agent（前端退化为纯人 / 无提案）")
            self._agent = None

    def _latest_frame(self) -> str | None:
        """逆序扫 `_feed`，取第一条含 `content.frame` 的事件（只取该字段，不碰游戏语义）。"""
        for raw in reversed(self._feed):
            try:
                ev = json.loads(raw)["event"]
                content = ev.get("content") or {}
            except (ValueError, KeyError, TypeError):
                continue
            if content.get("frame"):
                return content["frame"]
        return None

    def _receive_proposal(self, pm: ProposalMsg) -> None:
        """agent 推回的 proposal → 套上 round 转成跳 B `ProposalReq` 广播给 `/ui`。"""
        seq = pm.seq
        if self._pending is None or self._pending.ask.seq != seq:
            return  # 已了结或不是当前 pending：丢弃
        round_ = self._rounds.get(seq, 0)
        broadcast(
            self._ui,
            FromReviewBackendToFrontendProposalReq(
                seq=seq, proposal=pm.proposal, round=round_
            ).model_dump_json(),
        )
        self._rounds[seq] = round_ + 1

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
        """推一问、等人答 / run 断开，了结并记进历史；run 断开时返回 None。

        **不再自管超时**：timeout=None，后端无限等（人模式靠人答、AI 模式靠前端倒计时）。
        """
        # 步骤 1：编号、挂起、推给网页。
        self._seq += 1
        has_agent = self._agent is not None and self._agent.connected
        deadline = (time.time() + AI_COUNTDOWN) if has_agent else None
        ask = _to_ask(self._seq, req, deadline)
        answer: asyncio.Future[FromFrontendToReviewBackendAnswerReq] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending = _Pending(ask, answer)
        broadcast(self._ui, ask.model_dump_json())
        _say(f"第 {ask.seq} 问（{ask.kind}）：{ask.prompt}")

        # 步骤 2：有 agent 则经跳 C 发 seed（不阻塞）；人模式无倒计时。后端无限等。
        if has_agent:
            frame = self._latest_frame()
            self._rounds[ask.seq] = 0
            await self._agent.seed(ask.seq, ask, frame)

        gone = asyncio.ensure_future(conn.wait_closed())
        try:
            done, _ = await asyncio.wait(
                {answer, gone}, timeout=None, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            gone.cancel()
            self._pending = None
        if answer in done:
            by = answer_by(answer.result())
        elif gone in done:
            by = "harness_gone"
        else:
            by = "timeout"

        # 步骤 3：了结、广播、记历史；顺手关掉 agent 侧该 seq。
        if self._agent is not None:
            await self._agent.close(ask.seq)
        self._rounds.pop(ask.seq, None)
        settle = _settle(ask, answer.result() if answer in done else None, by)
        self._history.append((ask, settle))
        broadcast(self._ui, settle.model_dump_json())
        _say(f"第 {ask.seq} 问了结：{by}")
        if by == "harness_gone":
            return None
        return _to_resp(settle, answered=by in ("human", "agent"))

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
                try:
                    data = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if data.get("msg") == "discuss":
                    await self._discuss(raw)
                    continue
                resp = self._answer(raw)
                if resp is not None:
                    await conn.send(resp.model_dump_json())
        except ConnectionClosed:
            pass
        finally:
            self._ui.discard(conn)

    async def _discuss(self, raw: str | bytes) -> None:
        """收网页「发给 AI」：校验 seq + 非空 → 取最新帧 → 经跳 C 发 turn 给 agent。

        agent 推回新 proposal（round+1）后由监听协程广播。agent 没连上则丢弃打日志。
        """
        try:
            req = FromFrontendToReviewBackendDiscussReq.model_validate_json(raw)
        except ValidationError as exc:
            _say(f"网页发来看不懂的 discuss，丢弃：{exc.errors()[:1]}")
            return
        pending = self._pending
        if pending is None or pending.ask.seq != req.seq:
            _say(f"[agent] discuss 的 seq {req.seq} 不是当前 pending，丢弃")
            return
        if not req.text.strip():
            return
        if self._agent is None or not self._agent.connected:
            _say("[agent] 没有连上的 agent，discuss 丢弃")
            return
        frame = self._latest_frame()
        await self._agent.turn(req.seq, ChatTurn(role="human", text=req.text.strip()), frame)

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
        # 显式 `by="timeout"` 表示"无人决断，用默认"——即便内容为空也接受；
        # 其余 `by`（human / agent）必须与问相配（插话有 text、审有 verdict）。
        if req.by != "timeout" and (
            (pending.ask.kind == "inject" and req.text is None)
            or (pending.ask.kind == "audit" and req.verdict is None)
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


def _to_ask(seq: int, req: HarnessReq, deadline: float | None) -> FromReviewBackendToFrontendAskReq:
    """把跳 A 请求摊平成推给网页的一问。`deadline` 由调用方决定（有 agent → 倒计时；否则 None）。"""
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
        deadline=deadline,
    )


def answer_by(ans: FromFrontendToReviewBackendAnswerReq | None) -> str:
    """由答案判定 settle 的 `by`：空框（没填内容）= `timeout`；否则取 `ans.by`（human / agent）。"""
    if ans is None:
        return "timeout"
    filled = (ans.text not in (None, "")) or ans.verdict is not None
    if not filled:
        return "timeout"
    return ans.by


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
