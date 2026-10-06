"""inspect view 前置检测与拉起：批跑起 harness 之前，先保证结果层服务可用（用户 09-28 定）。

三态：端口已通（别人起的实例在跑）→ 不动；没在跑且 `inspect` CLI 可用 → **脱离批跑进程**
拉起（批跑结束 view 不陪葬），拉起后探端口确认；CLI 不在 PATH 或拉起后端口仍不通 → 显式跳过，
**不挡批跑**。inspect-ai 要到 R0 才装（plan2），在此之前本模块恒走"跳过"分支——预接线，装上即生效。
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

VIEW_PORT = 7575
"""inspect view 的默认端口（与 inspect-ai 官方默认一致）。"""

START_TIMEOUT = 5.0
"""拉起后等端口通的最长秒数；超时判跳过，不无限等。"""


def view_running(port: int = VIEW_PORT) -> bool:
    """探测 127.0.0.1:port 有没有服务在听（0.5s 连接超时，探不上即没在跑）。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def ensure_view(log_dir: Path, port: int = VIEW_PORT) -> str:
    """批跑前置：保证 inspect view 可用，返回一行人读状态。

    - 已在跑 → 不动别人的实例（inspect view 同端口会互杀，探测先行就是防这个）；
    - 拉起 → 子进程脱离批跑（Windows `DETACHED_PROCESS`，POSIX 新会话），输出落
      `<log_dir>/inspect_view.log` 供诊断；
    - 跳过 → CLI 不在 PATH（inspect-ai 未装）或拉起后端口始终不通。三种都只报告、不抛。
    """
    if view_running(port):
        return f"view 已在跑（127.0.0.1:{port}）"
    cli = _inspect_cli()
    if cli is None:
        return "view 跳过：inspect CLI 不在 PATH（inspect-ai 未装，R0 装上即自动生效）"
    log_dir.mkdir(parents=True, exist_ok=True)
    out = log_dir / "inspect_view.log"
    with out.open("ab") as stream:
        kwargs: dict[str, object] = {"stdout": stream, "stderr": subprocess.STDOUT}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(  # noqa: S603 —— CLI 路径来自 shutil.which，参数全是本项目常量
            [cli, "view", "--log-dir", str(log_dir), "--port", str(port)],
            **kwargs,  # type: ignore[arg-type]
        )
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if view_running(port):
            return f"view 已拉起 → http://127.0.0.1:{port}（输出：{out}）"
        time.sleep(0.3)
    return f"view 跳过：拉起后 {START_TIMEOUT:g}s 端口 {port} 仍不通（诊断看 {out}）"


def _inspect_cli() -> str | None:
    """`inspect` 可执行文件的路径；不在 PATH 为 None。"""
    return shutil.which("inspect")


__all__ = ["VIEW_PORT", "ensure_view", "view_running"]
