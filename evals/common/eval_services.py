"""评测专用 world 与 memory 服务生命周期。"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from evals.common.capture_services import (
    _memory_config,
    available_port,
    start_process,
    stop_process,
    wait_ready,
)
from evals.paths import REPO_ROOT

__all__ = ["eval_services"]


@contextmanager
def eval_services(
    *,
    world: bool,
    memory: bool,
    knowledge_source: Path | None = None,
    admin: bool = False,
    export_env: bool = True,
) -> Iterator[dict[str, str]]:
    """启动本次评测需要的隔离服务，并在离开时恢复环境与清理资源。"""
    root = Path(tempfile.mkdtemp(prefix="pokemon-eval-services-"))
    processes = []
    logs: list[Path] = []
    ports: set[int] = set()
    exported: dict[str, str | None] = {}
    exported_env = False
    try:
        env: dict[str, str] = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        if world:
            _prepare_service(
                name="world",
                requested=True,
                variable="MCP_WORLD_SERVER_URL",
                root=root,
                env=env,
                processes=processes,
                logs=logs,
                ports=ports,
            )
        if memory:
            _prepare_knowledge(root, knowledge_source)
            _prepare_service(
                name="memory",
                requested=True,
                variable="MCP_MEMORY_SERVER_URL",
                root=root,
                env=env,
                processes=processes,
                logs=logs,
                admin=admin,
                ports=ports,
            )
        if export_env:
            for key, value in env.items():
                exported[key] = os.environ.get(key)
                os.environ[key] = value
            exported_env = True
        yield env
    finally:
        if exported_env:
            _restore_environment(exported)
        try:
            stop_error: BaseException | None = None
            for process in reversed(processes):
                try:
                    stop_process(process)
                except BaseException as error:
                    if stop_error is None:
                        stop_error = error
            if stop_error is not None:
                raise stop_error
        finally:
            try:
                _copy_logs(logs)
            finally:
                shutil.rmtree(root, ignore_errors=True)


def _prepare_knowledge(root: Path, source: Path | None) -> None:
    """建立干净 knowledge collection，仅复制源目录内的 Markdown 文件。"""
    target = root / "memory" / "knowledge_memory"
    target.mkdir(parents=True, exist_ok=True)
    if source is None:
        return
    for path in source.glob("*.md"):
        if path.is_file():
            shutil.copy2(path, target / path.name)


def _prepare_service(
    *,
    name: str,
    requested: bool,
    variable: str,
    root: Path,
    env: dict[str, str],
    processes: list,
    logs: list[Path],
    ports: set[int],
    admin: bool = False,
) -> None:
    """复用已有服务地址，或启动本次所需服务并等待探活。"""
    if not requested:
        return
    existing = os.environ.get(variable)
    if existing:
        print(f"eval_services: reusing {variable}={existing}")
        env[variable] = existing
        return
    port = available_port()
    while port in ports:
        port = available_port()
    ports.add(port)
    url = f"http://127.0.0.1:{port}"
    env[variable] = url
    child_env = dict(os.environ)
    child_env.update(env)
    child_env.update(PYTHONPATH=str(REPO_ROOT), PYTHONUNBUFFERED="1")
    log = root / f"{name}.log"
    logs.append(log)
    if name == "world":
        arguments = [
            "-m",
            "pokemon_agent.mcp_servers.world_server",
            "--rom",
            str(REPO_ROOT / "assets" / "rom"),
            "--port",
            str(port),
        ]
    else:
        arguments = [
            "-m",
            "pokemon_agent.mcp_servers.memory_server",
            "--config",
            str(_memory_config(root, port)),
        ]
        if admin:
            arguments.append("--enable-admin")
        arguments.extend(["--port", str(port)])
    process = start_process(arguments, log, child_env)
    processes.append(process)
    wait_ready(process, url)


def _restore_environment(previous: dict[str, str | None]) -> None:
    """恢复导出前的变量值与缺失状态。"""
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _copy_logs(logs: list[Path]) -> None:
    """把本次启动服务的日志复制到带时间戳的评测产物目录。"""
    existing = [path for path in logs if path.is_file()]
    if not existing:
        return
    destination = (
        REPO_ROOT / "eval_results" / "eval_runs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )
    destination.mkdir(parents=True, exist_ok=False)
    for path in existing:
        shutil.copy2(path, destination / path.name)
