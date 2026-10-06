"""`WebReviewer`：`Reviewer` 的网页实现——run 进程里的 WebSocket 客户端，连常驻后端。

一问一答：把进程内的请求渲染成文本（`review_render.py`，与控制台同一份口径）→ 组跳 A 信封 →
经 `/harness` 发给后端 → 阻塞等回话 → 转回进程内的 Resp。它不起服务、不存状态、不重连。

**连不上就当场停**：构造时连后端，失败抛 `OSError`（宁可装配时炸，别等一局跑完才发现没人能接）。
**中途断了就降级**：本问与之后每一问都按默认值（插话空串、审认账）、`answered=False`，
每问打一行 `[review]` 日志——run 不因前端设施崩掉而作废（`docs/web_reviewer/spec.md` §5.3）。
**不走代理**：连的是本机回环地址，显式 `proxy=None`（本机开着 HTTP(S)_PROXY 时也不绕出去）。
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import ClientConnection, connect

from pokemon_agent.config import WEB_REVIEW_TIMEOUT
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewBackendAuditReq,
    FromHarnessToReviewBackendAuditResp,
    FromHarnessToReviewBackendInjectReq,
    FromHarnessToReviewBackendInjectResp,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)

from .review_render import audit_prompt, format_form, outcome_kind, render_events, render_outcome

DEFAULT_URL = "ws://127.0.0.1:8765"
"""后端缺省地址（与 `python -m pokemon_agent.review_backend` 的缺省端口一致）。"""

CONNECT_TIMEOUT_S = 5.0
"""构造时连后端的等待上限。"""

_Resp = TypeVar("_Resp", bound=BaseModel)


class WebReviewer:
    """网页实现：插话与审都转给常驻后端，由网页上的人答。"""

    def __init__(
        self, run_id: str, url: str = DEFAULT_URL, timeout: float | None = WEB_REVIEW_TIMEOUT
    ) -> None:
        """连后端的 `/harness`。

        run_id：这次 run 的标识，每一问都带上。
        url：后端地址（`ws://host:port`）。
        timeout：每一问等人的秒数；`None` 表示不自带超时——交给后端 / 前端 / agent 计时
          （`--review` 默认走这条，AI 模式由网页倒计时提交）；纯人路径传 `WEB_REVIEW_TIMEOUT`。
        失败：连不上 / 被拒（已有别的 run 连着）时抛 `OSError`。
        """
        self._run_id, self._url, self._timeout = run_id, url, timeout
        try:
            self._conn: ClientConnection | None = connect(
                f"{url}/harness", proxy=None, open_timeout=CONNECT_TIMEOUT_S
            )
        except (OSError, TimeoutError, InvalidHandshake, InvalidURI) as exc:
            raise OSError(
                f"连不上人在环后端 {url}（{exc}）——先在本机起 "
                "`python -m pokemon_agent.review_backend`，再开网页"
            ) from exc
        wait = f"{timeout:g}s" if timeout is not None else "∞（后端 / 前端 / agent 计时）"
        _say(f"已连上后端 {url}（run={run_id}，每问等 {wait}）")

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        """**插话**：表单渲染成文本交给后端，等网页上的人说一句（空串 = 没意见）。"""
        wire = FromHarnessToReviewBackendInjectReq(
            run_id=self._run_id,
            prompt=req.prompt,
            form_kind=req.form_kind,
            form_text=format_form(req.form),
            timeout_s=self._timeout,
        )
        resp = self._exchange(wire, FromHarnessToReviewBackendInjectResp)
        if resp is None:
            return FromHarnessToReviewerInjectResp(text="", answered=False)
        _say(f"第 {resp.seq} 问（插话）：{_summary(resp.answered, resp.text or '没意见')}")
        return FromHarnessToReviewerInjectResp(text=resp.text, answered=resp.answered)

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        """**审**：结论与被审对象的事件渲染成文本交给后端，等网页上的人认或推翻。"""
        wire = FromHarnessToReviewBackendAuditReq(
            run_id=self._run_id,
            episode_id=req.episode_id,
            task_id=req.task_id,
            prompt=audit_prompt(req),
            form_kind=outcome_kind(req.outcome),
            outcome_text=render_outcome(req),
            events=render_events(req.events),
            timeout_s=self._timeout,
        )
        resp = self._exchange(wire, FromHarnessToReviewBackendAuditResp)
        if resp is None:
            return FromHarnessToReviewerAuditResp(verdict=AuditVerdict.ACCEPT, answered=False)
        said = f"{resp.verdict.value}{('：' + resp.note) if resp.note else ''}"
        _say(f"第 {resp.seq} 问（审 {wire.form_kind}）：{_summary(resp.answered, said)}")
        return FromHarnessToReviewerAuditResp(
            verdict=resp.verdict, note=resp.note, answered=resp.answered
        )

    def close(self) -> None:
        """断开与后端的连接（run 结束时调；重复调用无害）。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _exchange(self, wire: BaseModel, resp_type: type[_Resp]) -> _Resp | None:
        """发一封、等一封；后端不在、断开、超时或回了看不懂的东西时降级为 None 并断开。"""
        if self._conn is None:
            _say("后端已断开，这一问按默认值处理")
            return None
        try:
            self._conn.send(wire.model_dump_json())
            raw = self._conn.recv(timeout=self._timeout)
            return resp_type.model_validate_json(raw)
        except (ConnectionClosed, TimeoutError, OSError, ValidationError) as exc:
            _say(f"后端断开或回话异常（{type(exc).__name__}: {exc}）——本问与之后都按默认值处理")
            self.close()
            return None


def _summary(answered: bool, said: str) -> str:
    """一问一答的日志摘要：没人答时注明是默认值。"""
    return said if answered else f"没人答，按默认值（{said}）"


def _say(line: str) -> None:
    """问人动态一行一条打到 stdout（带 flush）。"""
    print(f"[review] {line}", flush=True)


__all__ = ["DEFAULT_URL", "WebReviewer"]
