"""采集专用 world/memory 服务；独立端口和空目录，只清理本次子进程。"""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from evals.paths import REPO_ROOT


def available_port() -> int:
    """选择本机空端口；启动时若发生竞争由子进程明确报错。"""
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


def start_process(
    arguments: list[str], log: Path, environment: dict[str, str]
) -> subprocess.Popen[bytes]:
    """启动无窗口子进程；独占日志文件，不打印部署凭据。"""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("xb") as stream:
        return subprocess.Popen(
            [sys.executable, "-B", *arguments],
            cwd=REPO_ROOT,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )


def wait_ready(process: subprocess.Popen[bytes], address: str) -> None:
    """最多等待 60 秒探活；退出、坏状态或超时显式失败。"""
    deadline = time.monotonic() + 60
    with httpx.Client(timeout=2, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"service exited: {process.returncode}; see capture logs")
            try:
                response = client.get(address + "/health")
            except httpx.TransportError:
                time.sleep(0.5)
                continue
            if response.is_success and response.json().get("ready"):
                return
            time.sleep(0.5)
    raise TimeoutError(f"service not ready: {address}")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    """只停止本工具持有的子进程；已经结束的进程不再操作。"""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
            process.wait(timeout=15)
            return
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@contextmanager
def capture_services(directory: Path) -> Iterator[dict[str, str]]:
    """本次专用世界与空记忆；无论成功失败都关停服务，不删除产物。"""
    directory.mkdir(parents=True, exist_ok=False)
    world_port, memory_port = available_port(), available_port()
    while memory_port == world_port:
        memory_port = available_port()
    environment = dict(os.environ)
    environment.update(
        MCP_WORLD_SERVER_URL=f"http://127.0.0.1:{world_port}",
        MCP_MEMORY_SERVER_URL=f"http://127.0.0.1:{memory_port}",
        PYTHONPATH=str(REPO_ROOT),
        PYTHONUNBUFFERED="1",
        PYTHONIOENCODING="utf-8",
    )
    processes: list[subprocess.Popen[bytes]] = []
    try:
        world = start_process(
            [
                "-m",
                "pokemon_agent.mcp_servers.world_server",
                "--rom",
                str(REPO_ROOT / "assets/rom"),
                "--port",
                str(world_port),
            ],
            directory / "world.log",
            environment,
        )
        processes.append(world)
        wait_ready(world, environment["MCP_WORLD_SERVER_URL"])
        memory = start_process(
            [
                "-m",
                "pokemon_agent.mcp_servers.memory_server",
                "--config",
                str(_memory_config(directory, memory_port)),
                "--enable-admin",
                "--port",
                str(memory_port),
            ],
            directory / "memory.log",
            environment,
        )
        processes.append(memory)
        wait_ready(memory, environment["MCP_MEMORY_SERVER_URL"])
        yield environment
    finally:
        for process in reversed(processes):
            stop_process(process)


def _memory_config(directory: Path, port: int) -> Path:
    """为本次 memory MCP 生成独立落盘根与监听地址配置。"""
    path = directory / "memory-server-config.json"
    path.write_text(
        json.dumps(
            {
                "paths": {"memory": str(directory / "memory")},
                "services": {"memory_server_url": f"http://127.0.0.1:{port}"},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path
