"""MCP 运维面：env 加载、地址形状、health 路由、build 前探活。

**测试定位**（与 SPEC §十一致）：全部 pytest，不起真服务进程、不连真模型。
health 路由用 Starlette `TestClient`（进程内 ASGI）打；探活用 monkeypatch 顶掉
`httpx.get`（它测的是判定逻辑，不是网络栈）。
"""

from __future__ import annotations

import pathlib

import pytest
from starlette.testclient import TestClient

from pokemon_agent.env import env_str, load_env_file
from pokemon_agent.mcp_servers import common as server_common
from pokemon_agent.mcp_servers import memory_server
from pokemon_agent.mcpclient import (
    HEALTH_PATH as CLIENT_HEALTH_PATH,
)
from pokemon_agent.mcpclient import (
    McpTransportError,
    assert_mcp_server_ready,
    health_url,
    mcp_endpoint,
)


class _FakeEmbedder:
    dim = 4

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]


class _FakeReranker:
    def rerank(self, query: str, docs: list[str]) -> list[float]:
        return [0.0 for _ in docs]


def _build_capability(root: pathlib.Path):
    from pokemon_agent.memory.recall import MemoryCapability

    return MemoryCapability(
        embedding_provider=_FakeEmbedder(),
        reranker_provider=_FakeReranker(),
        memory_root=root,
    )


# ---- 一、env ----


def test_load_env_file_reads_keys_and_never_overrides_real_env(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 的条目进 os.environ；**真变量优先**（容器里注入的不被盘上文件盖掉）。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# 注释行\n"
        "\n"
        "MCP_MEMORY_SERVER_URL=http://127.0.0.1:8766\n"
        'QUOTED_KEY="带空格 的值"\n'
        "SINGLE_KEY='单引号'\n"
        "OVERRIDE_ME=from_file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OVERRIDE_ME", "from_real_env")
    monkeypatch.delenv("MCP_MEMORY_SERVER_URL", raising=False)

    assert load_env_file(env_file) == env_file

    assert env_str("MCP_MEMORY_SERVER_URL") == "http://127.0.0.1:8766"
    assert env_str("QUOTED_KEY") == "带空格 的值", "成对引号剥掉一层"
    assert env_str("SINGLE_KEY") == "单引号"
    assert env_str("OVERRIDE_ME") == "from_real_env", "真环境变量不被 .env 覆盖"


def test_env_empty_value_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """`KEY=` 是"预留了但没填"，不是"值是空串"——按未配处理，交给缺省分支。"""
    monkeypatch.setenv("MCP_MEMORY_SERVER_URL", "   ")
    assert env_str("MCP_MEMORY_SERVER_URL") is None
    assert env_str("MCP_MEMORY_SERVER_URL", "fallback") == "fallback"


def test_load_env_file_missing_is_a_noop(tmp_path: pathlib.Path) -> None:
    """文件不存在 → 返回 None、不抛（没配 env 是合法的进程内模式）。"""
    assert load_env_file(tmp_path / "nope.env") is None


# ---- 二、地址形状 ----


def test_url_shape_composes_from_base_without_doubling_slashes() -> None:
    """base + 协议常量：端点 `/mcp`、探活 `/health`。"""
    assert mcp_endpoint("http://127.0.0.1:8766") == "http://127.0.0.1:8766/mcp"
    assert mcp_endpoint("http://127.0.0.1:8766/") == "http://127.0.0.1:8766/mcp"
    assert health_url("http://127.0.0.1:8766") == "http://127.0.0.1:8766/health"


def test_health_path_constants_agree_across_server_and_client() -> None:
    """server 挂路由的路径与 client 探活的路径是两份字面量（两侧包不互相 import）——
    等值断言钉住，改一处忘了另一处这里会红。"""
    assert server_common.HEALTH_PATH == CLIENT_HEALTH_PATH
    assert server_common.MCP_PATH == "/mcp"


# ---- 三、health 路由 ----


def test_health_route_reports_ready_only_after_capability_injection(
    tmp_path: pathlib.Path,
) -> None:
    """进程活着但能力没注入 = 半启动：HTTP 仍 200，但 `ready=false`。

    这条是探活能挡住半启动状态的前提——如果未注入时返回 500，探活只能看到
    "连不上"，分不清"没起"和"起了没配好"。
    """
    memory_server._capability = None
    app = memory_server.mcp.streamable_http_app()
    with TestClient(app) as client:
        before = client.get(CLIENT_HEALTH_PATH)
        assert before.status_code == 200
        assert before.json()["ready"] is False
        assert before.json()["service"] == memory_server.SERVICE_NAME

        capability = _build_capability(tmp_path)
        memory_server.start(capability)
        try:
            after = client.get(CLIENT_HEALTH_PATH)
            assert after.status_code == 200
            body = after.json()
            assert body["status"] == "ok"
            assert body["ready"] is True
            assert body["admin"] is False
            assert body["root"] == str(capability.root), "探活要能看出连的是哪个库"
        finally:
            memory_server._capability = None


def test_health_is_not_a_mcp_tool() -> None:
    """health **不进能力面**：`tools/list` 里只有 recall / memorize。

    能力面是模型可见、可调用的动作清单；探活是运维动作，混进去只会稀释它。
    """
    assert CLIENT_HEALTH_PATH not in {"recall", "memorize"}


# ---- 四、build 前探活 ----


def _fake_response(status_code: int, payload: dict) -> object:
    class _Response:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self) -> dict:
            return payload

    return _Response()


def test_probe_passes_when_server_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _fake_response(
            200,
            {"status": "ok", "service": "pokemon-memory", "ready": True, "root": "/data/memory"},
        ),
    )
    health = assert_mcp_server_ready("http://127.0.0.1:8766", "memory")
    assert health["ready"] is True
    assert health["root"] == "/data/memory"


@pytest.mark.parametrize(
    ("payload", "status_code", "needle"),
    [
        ({"status": "ok", "ready": False}, 200, "能力没注入"),
        ({"status": "degraded", "ready": True}, 200, "健康检查未通过"),
        ({"status": "ok", "ready": True}, 503, "健康检查非 200"),
    ],
)
def test_probe_rejects_unhealthy_server(
    payload: dict, status_code: int, needle: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """三种不健康形态都必须就地抛错——挡在 run 之前，而不是跑一半静默丢账。"""
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(status_code, payload))
    with pytest.raises(McpTransportError, match=needle):
        assert_mcp_server_ready("http://127.0.0.1:8766", "memory")


def test_probe_reports_unreachable_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """连不上时的报错要带"先把服务起起来"——它与 503 的处置方式不同。"""
    import httpx

    def _boom(*_a: object, **_k: object) -> object:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _boom)
    with pytest.raises(McpTransportError, match="不可达"):
        assert_mcp_server_ready("http://127.0.0.1:8766", "memory")


def test_probe_rejects_empty_base_url() -> None:
    """空地址不该走到网络层——那是"没配"，装配点应当走进程内模式。"""
    with pytest.raises(AssertionError):
        assert_mcp_server_ready("  ", "memory")
