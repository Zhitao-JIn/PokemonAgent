"""落盘路径按仓库根解析，生效配置快照可事后核对。"""

import hashlib
import json
from pathlib import Path

from _harness_fixtures.app_config import app_config

from pokemon_agent.settings import load_config, resolve_path, write_snapshot
from pokemon_agent.settings.paths import REPO_ROOT


def test_relative_roots_resolve_against_the_repository_not_the_working_directory(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    paths = app_config(paths={"runs_root": "out", "memory": "mem"}).paths

    assert resolve_path(paths, "memory") == REPO_ROOT / "out" / "mem"
    assert resolve_path(paths, "trace") == REPO_ROOT / "out" / "tracelog"


def test_absolute_roots_and_entries_are_used_as_given(tmp_path: Path) -> None:
    paths = app_config(paths={"runs_root": str(tmp_path)}).paths

    assert resolve_path(paths, "memory") == tmp_path / "memory"


def test_snapshot_records_sources_digest_and_effective_values(tmp_path: Path) -> None:
    resolved = load_config()
    prompts = {
        "zeta": {"version": "v2", "hash": "b" * 64},
        "alpha": {"version": "v1", "hash": "a" * 64},
    }

    first = write_snapshot(resolved, tmp_path / "snap", "run-1", prompts)
    again = write_snapshot(resolved, tmp_path / "snap", "run-1", prompts)

    payload = json.loads(first.read_text(encoding="utf-8"))
    assert first == again and first.read_bytes() == again.read_bytes()
    assert payload["prompts"] == {
        "alpha": {"version": "v1", "hash": "a" * 64},
        "zeta": {"version": "v2", "hash": "b" * 64},
    }
    identity = json.dumps(
        {"config": payload["config"], "prompts": payload["prompts"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    assert payload["sha256"] == expected_hash
    assert first.name == f"run-1-{expected_hash[:8]}.json"
    assert payload["sources"] == list(resolved.sources)
    assert payload["config"]["budget"]["max_episodes"] == 10
