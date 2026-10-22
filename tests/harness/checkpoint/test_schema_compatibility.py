"""旧指纹在装配和恢复世界前拒绝；相符清单仍可读取。"""

from pathlib import Path
from typing import NoReturn

import pytest

from pokemon_agent.harness.checkpoint import CheckpointIncompatible, open_branch, read_manifest
from pokemon_agent.harness.checkpoint.manifest import (
    CheckpointManifest,
    CodeStamp,
    state_schema_hash,
)
from pokemon_agent.harness.run.run_state import RunState


def manifest_path(tmp_path: Path, fingerprint: str) -> Path:
    world = tmp_path / "world.state"
    memory = tmp_path / "memory.zip"
    world.write_bytes(b"world")
    memory.write_bytes(b"memory")
    manifest = CheckpointManifest(
        checkpoint_id="old-schema",
        level="run",
        run_id="r",
        branch="main",
        run_state=RunState.model_validate(
            {"run_id": "r", "run_goal": {"goal": "g", "criteria": "c"}, "goals": []}
        ),
        world_file=world.name,
        memory_archive=str(memory),
        code=CodeStamp(git_commit="test", git_dirty=False, state_schema_hash=fingerprint),
        created_at="test",
    )
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    return path


def test_old_schema_checkpoint_is_rejected_before_assembly_with_a_clear_error(
    tmp_path: Path,
) -> None:
    path = manifest_path(tmp_path, "95057cca4fffb08b")

    def unexpected_assembly(branch: str) -> NoReturn:
        raise AssertionError("incompatible checkpoint must not assemble a branch")

    with pytest.raises(
        CheckpointIncompatible, match="old-schema.*状态结构与当前代码不同，拒绝加载"
    ):
        open_branch(path, unexpected_assembly)


def test_matching_schema_manifest_remains_readable(tmp_path: Path) -> None:
    path = manifest_path(tmp_path, state_schema_hash())

    manifest = read_manifest(path)

    assert manifest.code.state_schema_hash == state_schema_hash()
    assert manifest.run_state.run_id == "r"
