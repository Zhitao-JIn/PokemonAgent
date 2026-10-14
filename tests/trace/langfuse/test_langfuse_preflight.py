"""`assert_server_ready` 的用法示范：启动前探针在服务不在场时要当场报错。

**全部离线**：httpx 的 `get` 被猴补掉，不连任何服务。
"""

from __future__ import annotations

import pytest

from pokemon_agent.trace.langfuse_support import assert_server_ready


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"status": "OK", "version": "4.46.0"}

    def json(self) -> dict:
        return self._payload


def _patch_get(monkeypatch: pytest.MonkeyPatch, responder) -> None:
    import httpx

    monkeypatch.setattr(httpx, "get", responder)


def test_a_healthy_server_reports_its_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 + status=OK → 返回版本字符串，供调用方打进启动日志。"""

    def _respond(url, **kwargs):
        assert url == "http://localhost:3000/api/public/health"
        assert kwargs["trust_env"] is False, "探针只连本机，绝不过系统代理"
        return _FakeResponse()

    _patch_get(monkeypatch, _respond)

    version = assert_server_ready("http://localhost:3000")

    assert version == "4.46.0"


def test_an_unreachable_server_blocks_the_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    """服务没起 → RuntimeError 且报错里带 URL——挡在 run 开始之前。"""
    import httpx

    def _respond(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    _patch_get(monkeypatch, _respond)

    with pytest.raises(RuntimeError, match="http://localhost:3000"):
        assert_server_ready("http://localhost:3000")


def test_an_unhealthy_server_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 200 或 status != OK 都算失败——不能拿半个能用的服务开跑。"""

    _patch_get(monkeypatch, lambda url, **kwargs: _FakeResponse(status_code=502))

    with pytest.raises(RuntimeError, match="502"):
        assert_server_ready("http://localhost:3000")

    _patch_get(
        monkeypatch,
        lambda url, **kwargs: _FakeResponse(payload={"status": "degraded"}),
    )

    with pytest.raises(RuntimeError, match="健康检查"):
        assert_server_ready("http://localhost:3000")


def test_a_missing_base_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量没配（也没传参）→ 明确报错，而不是去探一个空 URL。"""
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="LANGFUSE_BASE_URL"):
        assert_server_ready()
