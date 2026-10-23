"""评测服务上下文的隔离、配置与清理用法。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import evals.common.eval_services as services


def _install_fakes(monkeypatch, tmp_path: Path, *, fail_ready: str | None = None):
    monkeypatch.delenv("MCP_WORLD_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_MEMORY_SERVER_URL", raising=False)
    calls: dict[str, list] = {"start": [], "ready": [], "stop": []}
    roots = iter([tmp_path / f"service-root-{index}" for index in range(20)])
    ports = iter(range(41000, 41020))

    def make_temp(**_kwargs):
        root = next(roots)
        root.mkdir()
        return str(root)

    def start(arguments, log, environment):
        process = SimpleNamespace(name=Path(log).stem, returncode=None)
        Path(log).write_text(process.name, encoding="utf-8")
        calls["start"].append((arguments, Path(log), environment, process))
        return process

    def ready(process, address):
        calls["ready"].append((process, address))
        if process.name == fail_ready:
            raise RuntimeError("service failed readiness")

    def stop(process):
        calls["stop"].append(process)

    def config(root, port):
        path = root / "memory-server-config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{port}", encoding="utf-8")
        return path

    monkeypatch.setattr(services.tempfile, "mkdtemp", make_temp)
    monkeypatch.setattr(services, "available_port", lambda: next(ports))
    monkeypatch.setattr(services, "start_process", start)
    monkeypatch.setattr(services, "wait_ready", ready)
    monkeypatch.setattr(services, "stop_process", stop)
    monkeypatch.setattr(services, "_memory_config", config)
    monkeypatch.setattr(services, "REPO_ROOT", tmp_path)
    return calls


def test_eval_services_exports_clean_urls_and_restores_environment(monkeypatch, tmp_path) -> None:
    calls = _install_fakes(monkeypatch, tmp_path)
    monkeypatch.delenv("MCP_WORLD_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_MEMORY_SERVER_URL", raising=False)
    monkeypatch.setenv("PYTHONUTF8", "before")
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    with services.eval_services(world=True, memory=True) as environment:
        assert environment["MCP_WORLD_SERVER_URL"] == "http://127.0.0.1:41000"
        assert environment["MCP_MEMORY_SERVER_URL"] == "http://127.0.0.1:41001"
        service_urls = [value for key, value in environment.items() if key.startswith("MCP_")]
        assert all(not value.endswith("/") and "/mcp" not in value for value in service_urls)
        assert environment["PYTHONUTF8"] == os.environ["PYTHONUTF8"] == "1"
        assert environment["PYTHONIOENCODING"] == os.environ["PYTHONIOENCODING"] == "utf-8"

    assert os.environ["PYTHONUTF8"] == "before"
    assert "PYTHONIOENCODING" not in os.environ
    assert len(calls["start"]) == 2
    assert len(calls["stop"]) == 2
    assert not (tmp_path / "service-root-0").exists()
    assert not (tmp_path / "service-root-1").exists()
    copied = list((tmp_path / "eval_results" / "eval_runs").glob("*/*.log"))
    assert {path.name for path in copied} == {"world.log", "memory.log"}


def test_eval_services_without_export_never_changes_parent_environment(
    monkeypatch, tmp_path
) -> None:
    _install_fakes(monkeypatch, tmp_path)
    for key in ("MCP_WORLD_SERVER_URL", "MCP_MEMORY_SERVER_URL", "PYTHONUTF8", "PYTHONIOENCODING"):
        monkeypatch.delenv(key, raising=False)

    with services.eval_services(world=True, memory=True, export_env=False) as environment:
        assert environment["PYTHONUTF8"] == "1"
        assert environment["PYTHONIOENCODING"] == "utf-8"
        assert all(key not in os.environ for key in environment)

    assert all(key not in os.environ for key in environment)


def test_eval_services_reuses_existing_urls_and_starts_only_missing_service(
    monkeypatch, tmp_path
) -> None:
    calls = _install_fakes(monkeypatch, tmp_path)
    monkeypatch.setenv("MCP_WORLD_SERVER_URL", "http://world.example")
    monkeypatch.delenv("MCP_MEMORY_SERVER_URL", raising=False)

    with services.eval_services(world=True, memory=True, export_env=False) as environment:
        assert environment["MCP_WORLD_SERVER_URL"] == "http://world.example"
        assert environment["MCP_MEMORY_SERVER_URL"] == "http://127.0.0.1:41000"

    assert len(calls["start"]) == len(calls["stop"]) == 1
    assert "world" not in calls["start"][0][1].name


def test_eval_services_reuses_both_urls_without_starting_processes(monkeypatch, tmp_path) -> None:
    calls = _install_fakes(monkeypatch, tmp_path)
    monkeypatch.setenv("MCP_WORLD_SERVER_URL", "http://world.example")
    monkeypatch.setenv("MCP_MEMORY_SERVER_URL", "http://memory.example")

    with services.eval_services(world=True, memory=True, export_env=False) as environment:
        assert environment["MCP_WORLD_SERVER_URL"] == "http://world.example"
        assert environment["MCP_MEMORY_SERVER_URL"] == "http://memory.example"

    assert calls["start"] == calls["stop"] == []


def test_eval_services_copies_only_knowledge_markdown_and_honors_admin(
    monkeypatch, tmp_path
) -> None:
    calls = _install_fakes(monkeypatch, tmp_path)
    source = tmp_path / "knowledge-source"
    source.mkdir()
    (source / "lesson.md").write_text("lesson", encoding="utf-8")
    (source / "index.json").write_text("{}", encoding="utf-8")
    (source / "vectors.jsonl").write_text("{}", encoding="utf-8")

    with services.eval_services(
        world=False, memory=True, knowledge_source=source, admin=True, export_env=False
    ):
        target = tmp_path / "service-root-0" / "memory" / "knowledge_memory"
        assert [path.name for path in target.iterdir()] == ["lesson.md"]
        arguments = calls["start"][0][0]
        assert "--enable-admin" in arguments

    with services.eval_services(world=False, memory=True, admin=False, export_env=False):
        target = tmp_path / "service-root-1" / "memory" / "knowledge_memory"
        assert list(target.iterdir()) == []
        assert "--enable-admin" not in calls["start"][1][0]


def test_eval_services_skips_unrequested_services_and_knowledge_copy(monkeypatch, tmp_path) -> None:
    calls = _install_fakes(monkeypatch, tmp_path)
    source = tmp_path / "knowledge-source"
    source.mkdir()
    (source / "lesson.md").write_text("lesson", encoding="utf-8")

    with services.eval_services(
        world=True, memory=False, knowledge_source=source, export_env=False
    ) as env:
        assert "MCP_WORLD_SERVER_URL" in env and "MCP_MEMORY_SERVER_URL" not in env
    assert len(calls["start"]) == 1
    assert calls["start"][0][0][1] == "pokemon_agent.mcp_servers.world_server"
    assert not (tmp_path / "service-root-0" / "memory").exists()

    with services.eval_services(
        world=False, memory=False, knowledge_source=source, export_env=False
    ) as env:
        assert "MCP_WORLD_SERVER_URL" not in env and "MCP_MEMORY_SERVER_URL" not in env
    assert len(calls["start"]) == 1


@pytest.mark.parametrize("failure", [None, RuntimeError("block failed"), asyncio.CancelledError()])
def test_eval_services_always_stops_copies_logs_and_removes_temp_root(
    monkeypatch, tmp_path, failure
) -> None:
    calls = _install_fakes(monkeypatch, tmp_path)
    root = tmp_path / "service-root-0"

    if failure is None:
        with services.eval_services(world=True, memory=False, export_env=False):
            pass
    else:
        with (
            pytest.raises(type(failure)),
            services.eval_services(world=True, memory=False, export_env=False),
        ):
            raise failure

    assert len(calls["stop"]) == 1
    assert not root.exists()
    assert len(list((tmp_path / "eval_results" / "eval_runs").glob("*/world.log"))) == 1


def test_eval_services_cleans_up_when_second_service_fails_to_start(monkeypatch, tmp_path) -> None:
    calls = _install_fakes(monkeypatch, tmp_path, fail_ready="memory")
    monkeypatch.delenv("MCP_WORLD_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_MEMORY_SERVER_URL", raising=False)

    with (
        pytest.raises(RuntimeError, match="readiness"),
        services.eval_services(world=True, memory=True, export_env=False),
    ):
        pytest.fail("context should not yield before all services are ready")

    assert len(calls["start"]) == 2
    assert len(calls["stop"]) == 2
    assert not (tmp_path / "service-root-0").exists()
    copied = list((tmp_path / "eval_results" / "eval_runs").glob("*/*.log"))
    assert {path.name for path in copied} == {"world.log", "memory.log"}


def test_eval_services_overlapping_contexts_are_independent(monkeypatch, tmp_path) -> None:
    calls = _install_fakes(monkeypatch, tmp_path)
    monkeypatch.delenv("MCP_WORLD_SERVER_URL", raising=False)

    first = services.eval_services(world=True, memory=False, export_env=False)
    first_env = first.__enter__()
    second = services.eval_services(world=True, memory=False, export_env=False)
    second_env = second.__enter__()
    assert first_env["MCP_WORLD_SERVER_URL"] != second_env["MCP_WORLD_SERVER_URL"]
    assert (tmp_path / "service-root-0") != (tmp_path / "service-root-1")

    first.__exit__(None, None, None)
    assert len(calls["stop"]) == 1
    assert calls["stop"][0] is calls["start"][0][3]

    second.__exit__(None, None, None)
    assert len(calls["stop"]) == 2
