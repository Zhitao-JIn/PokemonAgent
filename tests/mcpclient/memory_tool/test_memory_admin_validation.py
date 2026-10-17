"""通过 MCP 验证管理面的注册、完整性、上限、互斥与坏归档拒绝。"""

from __future__ import annotations

import base64
import hashlib
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from _doubles.memory_server import act, recall, server_archive_limit
from _doubles.memory_server import remote as remote
from starlette.testclient import TestClient

from pokemon_agent.mcp_servers import common, memory_server
from pokemon_agent.mcpclient import client as client_module
from pokemon_agent.mcpclient import memory_tool
from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.mcpclient.memory_tool import MemoryAdminDisabled
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRestoreMemoryReq,
    FromHarnessToMemoryToolSnapshotMemoryReq,
)


def state(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "snapshots" not in path.relative_to(root).parts
    }


@pytest.mark.parametrize(
    ("entry", "mixed"),
    [
        ("step_memory\\x", False),
        ("../x", True),
        ("/absolute", False),
        ("C:escape", True),
    ],
)
def test_unsafe_entries_reject_the_entire_archive_before_any_deletion(
    tmp_path, remote, mixed, entry
):
    server, tool = remote
    delegate, root = tool._client, server.root
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(1)]))
    before, files = recall(tool), state(root)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        if mixed:
            for name, data in files.items():
                archive.writestr(name.replace("\\", "/"), data)
        info = zipfile.ZipInfo(entry)
        info.filename = entry
        archive.writestr(info, "unsafe")

    with pytest.raises(AssertionError, match="不安全"):
        delegate.restore(bad)

    assert recall(tool) == before
    assert len(recall(tool)) == 1
    assert state(root) == files


def test_non_zip_is_rejected_without_changing_the_library(tmp_path, remote):
    server, tool = remote
    delegate, root = tool._client, server.root
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(1)]))
    before, files = recall(tool), state(root)
    bad = tmp_path / "not_zip"
    bad.write_bytes(b"not a zip")

    with pytest.raises((AssertionError, zipfile.BadZipFile)):
        delegate.restore(bad)

    assert recall(tool) == before
    assert state(root) == files


@pytest.mark.parametrize("change", ["sha256", "archive_base64"])
def test_transport_corruption_does_not_change_the_library(remote, change):
    server, tool = remote
    delegate = tool._client
    client = delegate._client
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(1)]))
    data = delegate.snapshot("a").read_bytes()
    arguments = {
        "archive_base64": base64.b64encode(data).decode(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    arguments[change] = "bad!"
    before, files = recall(tool), state(server.root)

    result = client.call_tool_sync("restore_memory", arguments)

    assert result["code"] == "rejected" and result["ok"] is False
    assert recall(tool) == before
    assert state(server.root) == files


def test_corrupt_snapshot_response_cannot_overwrite_an_existing_archive(remote, monkeypatch):
    _, tool = remote
    delegate = tool._client
    client = delegate._client
    archive = delegate.snapshot("a")
    before = archive.read_bytes()
    original = client.call_tool_sync

    def corrupt(name, arguments):
        result = original(name, arguments)
        result["data"]["sha256"] = "bad"
        return result

    monkeypatch.setattr(client, "call_tool_sync", corrupt)
    with pytest.raises(ValueError, match="sha256"):
        delegate.snapshot("a")

    assert archive.read_bytes() == before
    assert not list(archive.parent.glob("*.tmp"))


def test_client_rejects_an_oversized_archive_before_sending(remote, tmp_path, monkeypatch):
    _, tool = remote
    delegate = tool._client
    client = delegate._client
    assert "restore_memory" in client.registry
    calls = []
    monkeypatch.setattr(client, "call_tool_sync", lambda *args: calls.append(args))
    monkeypatch.setattr(memory_tool, "MAX_ARCHIVE_BYTES", 1)
    archive = tmp_path / "big.zip"
    archive.write_bytes(b"xx")

    with pytest.raises(ValueError, match="MAX_ARCHIVE_BYTES"):
        delegate.restore(archive)

    assert not calls


def test_server_rejects_oversized_snapshots_and_restore_payloads(remote):
    _, tool = remote
    delegate = tool._client
    client = delegate._client
    data = delegate.snapshot("a").read_bytes()
    with server_archive_limit(1):
        snapshot = client.call_tool_sync("snapshot_memory", {"name": "a"})
        restore = client.call_tool_sync(
            "restore_memory",
            {
                "archive_base64": base64.b64encode(data).decode(),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )

    assert snapshot["code"] == restore["code"] == "rejected"


def test_admin_tools_and_health_follow_the_enable_admin_switch(remote):
    server, tool = remote
    delegate = tool._client
    client = delegate._client
    assert set(client.registry) == {"recall", "memorize", "snapshot_memory", "restore_memory"}
    with TestClient(memory_server.mcp.streamable_http_app()) as http:
        assert http.get("/health").json()["admin"] is True
        memory_server.start(server)
        client._registry = None
        assert set(client.registry) == {"recall", "memorize"}
        assert http.get("/health").json()["admin"] is False
    with pytest.raises(MemoryAdminDisabled, match="--enable-admin"):
        delegate.snapshot("a")
    with pytest.raises(MemoryAdminDisabled, match="--enable-admin"):
        delegate.restore("anywhere.zip")


def test_factory_uses_only_the_client_root_for_snapshots(remote, tmp_path, monkeypatch):
    server, connected = remote
    client = connected._client._client
    monkeypatch.setattr(client_module, "McpClient", lambda endpoint: client)
    root = tmp_path / "another_client"

    tool = MemoryTool.build(memory_root=root, memory_server_url="http://example")
    archive = tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="a"))

    assert Path(archive.archive) == root / "snapshots" / "a.zip"
    assert server.root != root


def test_factory_defaults_client_snapshots_to_launch_directory(remote, tmp_path, monkeypatch):
    server, connected = remote
    client = connected._client._client
    monkeypatch.setattr(client_module, "McpClient", lambda endpoint: client)
    monkeypatch.chdir(tmp_path)

    tool = MemoryTool.build(memory_server_url="http://example")
    archive = tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="a"))

    assert Path(archive.archive) == tmp_path / "memory" / "snapshots" / "a.zip"
    assert server.root != tmp_path / "memory"


def test_memorize_cannot_interleave_with_restore(remote, monkeypatch):
    server, tool = remote
    delegate = tool._client
    data = delegate.snapshot("a").read_bytes()
    entered, release, wrote = threading.Event(), threading.Event(), threading.Event()
    original = server.restore

    def slow(archive):
        entered.set()
        assert release.wait(5)
        return original(archive)

    monkeypatch.setattr(server, "restore", slow)
    monkeypatch.setattr(server, "memorize", lambda records: wrote.set() or [])
    with ThreadPoolExecutor(2) as workers:
        restoring = workers.submit(
            memory_server.restore_memory,
            base64.b64encode(data).decode(),
            hashlib.sha256(data).hexdigest(),
        )
        assert entered.wait(5)
        writing = workers.submit(memory_server.memorize, [])
        try:
            assert not wrote.wait(0.1)
        finally:
            release.set()
        assert restoring.result()["ok"] and writing.result()["ok"]
    assert wrote.is_set()


def test_archive_limits_agree_between_client_and_server():
    assert common.MAX_ARCHIVE_BYTES == memory_tool.MAX_ARCHIVE_BYTES == 256 * 1024 * 1024


def test_snapshot_crosses_roots_and_restores_from_an_arbitrary_path(tmp_path: Path, remote):
    server, tool = remote
    delegate = tool._client
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(1)]))
    before, files = recall(tool), state(server.root)

    archive = delegate.snapshot("a")
    external = tmp_path / "elsewhere" / "other.zip"
    external.parent.mkdir()
    shutil.copy2(archive, external)
    delegate.snapshot("a")
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(2)]))
    unpacked = delegate.restore(external)

    assert archive == tmp_path / "client" / "snapshots" / "a.zip"
    assert (server.root / "snapshots" / "a.zip").is_file()
    assert not list(archive.parent.glob("*.tmp"))
    assert unpacked == 2
    assert recall(tool) == before
    assert state(server.root) == files
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(2)]))
    assert len(recall(tool)) == 2


def test_own_snapshots_with_harmless_root_files_are_accepted(tmp_path: Path, remote):
    server, tool = remote
    root = server.root
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(1)]))
    (root / "notes.txt").write_text("harmless", encoding="utf-8")
    before = recall(tool)

    archive = tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="a"))
    tool.memorize(FromHarnessToMemoryToolMemorizeReq(records=[act(2)]))
    tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=archive.archive))

    assert recall(tool) == before
    assert (root / "notes.txt").read_text(encoding="utf-8") == "harmless"
