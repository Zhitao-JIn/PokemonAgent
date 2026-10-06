"""mcp_servers 共享件：统一返回信封与结局码词表。

所有 MCP tool 的返回统一为信封 dict（§SPEC 3.1）：

    {"ok": bool, "code": str, "data": ..., "events": [...], "error": str|null}

transport 级失败（JSON-RPC error）不经信封——由 mcpclient 翻译成 Python 异常。
"""

from __future__ import annotations

from typing import Any

HEALTH_PATH = "/health"
"""健康检查路由（普通 HTTP，**不是 MCP tool**）。

为什么不注册成 tool：`tools/list` 是**能力面**（模型可见、可调用的动作清单），
混进一个 `health` 会稀释它；健康检查是运维动作，走 Starlette 自定义路由更贴切
（curl / 探活脚本直接打，不必懂 MCP）。

**与 `mcpclient/client.py::HEALTH_PATH` 是两份字面量**（分处两个进程侧的包，
互相 import 会把 client 绑到 server 代码上）——由 `tests/test_mcp_health.py`
的等值断言钉住，改一处忘了另一处测试会红。
"""

MCP_PATH = "/mcp"
"""MCP Streamable HTTP 挂载路径（FastMCP 的默认值，写出来是为了让探活与
server 启动参数对得上一个明确的数）。"""

_CODES: frozenset[str] = frozenset(
    {
        "ok",
        "rejected",
        "blocked",
        "off_course",
        "not_converging",
        "budget_exhausted",
        "battle_started",
        "choice_presented",
        "map_changed",
        "no_encounter",
        "no_target",
        "no_response",
        "not_sold_here",
        "not_in_bag",
        "count_limit",
        "insufficient_funds",
        "insufficient_stock",
        "verify_failed",
        "warp_failed",
        "wrong_scene",
        "timeout",
        "still_talking",
        "perception_failed",
        "unsupported_map",
        "stalled",
    }
)
"""结局码词表（§SPEC 3.3）。server 只产这些 code；新增走本表 + SPEC 同步。"""


def envelope(
    data: Any = None,  # noqa: ANN401 —— 信封载荷是任意 JSON 化结构
    *,
    code: str = "ok",
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """成功信封。data 为载荷；events 为裸事件流（memory 能力面恒为空列表）。"""
    assert code in _CODES, f"unknown outcome code: {code!r}"
    return {
        "ok": code == "ok",
        "code": code,
        "data": data,
        "events": events if events is not None else [],
        "error": None,
    }


def health_payload(
    service: str,
    *,
    ready: bool,
    root: str | None = None,
    **extra: Any,  # noqa: ANN401 —— 运维载荷按需扩展，形状不固定
) -> dict[str, Any]:
    """健康检查载荷（§3 外的运维面，不进 `tools/list`）。

    `ready`：**能力是否已注入**（`start()` 走过没有）。进程活着但能力没注入是
    半启动状态——探活要把它认出来（`assert_mcp_server_ready` 据此报错），
    不能因为 HTTP 200 就放行。

    `root`：数据落盘根（memory = 记忆库根、world = ROM/存档所在），便于一眼
    确认"连的是不是我以为的那个库"。
    """
    payload: dict[str, Any] = {
        "status": "ok",
        "service": service,
        "ready": ready,
        "root": root,
    }
    payload.update(extra)
    return payload


def fail(
    code: str,
    error: str,
    data: Any = None,  # noqa: ANN401 —— 同上
    *,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """失败信封。code 为失败结局码（≠ok），error 为人类可读补充。"""
    assert code in _CODES and code != "ok", f"bad failure code: {code!r}"
    return {
        "ok": False,
        "code": code,
        "data": data,
        "events": events if events is not None else [],
        "error": error,
    }
