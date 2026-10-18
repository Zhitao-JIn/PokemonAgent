"""`WebReviewer(timeout=None)`：构造不断言正值，`_exchange` 用 `recv(None)` 阻塞、不叠 GRACE。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from _review_context import review_context

from pokemon_agent.harness.web_reviewer import WebReviewer
from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)


def _fake_conn() -> MagicMock:
    conn = MagicMock()
    resp = FromHarnessToReviewerInjectResp(seq=1, text="", answered=False, by="none")
    conn.recv.return_value = resp.model_dump_json()
    return conn


def _inject_req() -> FromHarnessToReviewerInjectReq:
    return FromHarnessToReviewerInjectReq(
        prompt="p", form={}, form_kind="x", context=review_context()
    )


def test_timeout_none_recv_none_no_grace() -> None:
    """`timeout=None` → `recv(None)`（阻塞到后端 settle），不叠 `+GRACE_S`。"""
    conn = _fake_conn()
    with patch("pokemon_agent.harness.web_reviewer.connect", return_value=conn):
        reviewer = WebReviewer("t", url="ws://x", timeout=None)
        reviewer.inject(_inject_req())
    conn.recv.assert_called_once_with(timeout=None)


def test_timeout_value_passed_through() -> None:
    """仍是数值时，原样下传，不叠 GRACE。"""
    conn = _fake_conn()
    with patch("pokemon_agent.harness.web_reviewer.connect", return_value=conn):
        reviewer = WebReviewer("t", url="ws://x", timeout=42)
        reviewer.inject(_inject_req())
    conn.recv.assert_called_once_with(timeout=42)


def test_construct_without_assert() -> None:
    """`timeout=None` 不再触发 `assert timeout > 0`。"""
    conn = _fake_conn()
    with patch("pokemon_agent.harness.web_reviewer.connect", return_value=conn):
        reviewer = WebReviewer("t", url="ws://x", timeout=None)
    assert reviewer._timeout is None
