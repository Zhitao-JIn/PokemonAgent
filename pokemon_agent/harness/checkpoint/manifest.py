"""存档清单：把世界存档、记忆快照与 run 图状态（原件或定位）绑成一个 checkpoint（spec v2 §四）。

清单由 checkpointer 产出，schema 归本模块（按产出地归档）。读写只在本文件：原子写、读时校验。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from ..episode.episode_state import EpisodeRunState
from ..run.run_state import RunState
from ..task.task_state import TaskState
from .errors import CheckpointCorrupt, CheckpointNotFound

Level = Literal["run", "episode"]
MANIFEST_FILENAME = "manifest.json"
WORLD_FILENAME = "world.state"


class GraphRef(BaseModel):
    """run 图"进 `act` 前"那一条 checkpoint 在 saver 里的定位（根图，`checkpoint_ns` 恒为空）。"""

    thread_id: str
    checkpoint_ns: str
    checkpoint_id: str


class LineageLink(BaseModel):
    """血缘的一环：某条祖先执行线，以及本线从它分叉的那一点。"""

    branch: str = Field(description="祖先执行线名")
    fork_uuid: str = Field(description="分叉点事件 uuid（祖先线在存档时的最后一条账）")
    fork_ts: float = Field(description="分叉点事件 ts")
    checkpoint_id: str = Field(description="从哪份存档分叉")


class CodeStamp(BaseModel):
    """存档时的代码版本。`state_schema_hash` 不同即拒绝加载；git commit 不同只告警。"""

    git_commit: str
    git_dirty: bool | None = Field(description="工作区是否有未提交改动；None = 查不到")
    state_schema_hash: str


class CheckpointManifest(BaseModel):
    """一份存档的清单。**不变式**：run 级带 `run_state`；episode 级带 `episode_id` 与 `run_ref`。"""

    checkpoint_id: str
    level: Level
    run_id: str
    branch: str
    lineage: list[LineageLink] = Field(description="存档所在执行线的祖先，由根到父；main 为空")
    episode_id: str | None = Field(default=None, description="episode 级：这份存档之后要派的那一局")
    run_state: RunState | None = Field(default=None, description="run 级：进图前的 RunState 原件")
    run_ref: GraphRef | None = Field(
        default=None, description="episode 级：run 图进 `act` 前那一条"
    )
    world_file: str
    memory_archive: str = Field(
        description="记忆 zip 的路径，相对进程启动目录（`launch_relative`）"
    )
    last_event_uuid: str = Field(description="存档时本执行线最后一条账；run 级为空（未开账）")
    last_event_ts: float
    code: CodeStamp
    models: dict[str, str] = Field(default_factory=dict)
    created_at: str

    @model_validator(mode="after")
    def _level_matches_contents(self) -> CheckpointManifest:
        """级别与内容一一对应——违反说明写清单的代码有 bug。"""
        expected = {"run": (True, False, False), "episode": (False, True, True)}[self.level]
        actual = (self.run_state is not None, self.run_ref is not None, self.episode_id is not None)
        if actual != expected:
            raise ValueError(f"{self.level} 级清单内容不符：{actual}，应为 {expected}")
        return self


def launch_relative(path: str | Path) -> str:
    """落进清单与账里的路径：**相对进程启动目录**，分隔符一律 `/`（读时按启动目录解析）。

    工作目录整体搬走、换机器、换操作系统都还能恢复——只要从同一个相对位置启动。
    与启动目录不在同一个盘（Windows 跨盘符）算不出相对路径时，退回绝对路径。
    """
    try:
        return Path(os.path.relpath(Path(path).resolve(), Path.cwd().resolve())).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def state_schema_hash() -> str:
    """三种状态模型的 JSON Schema 合起来的哈希：状态结构变了，旧存档就读不回来。"""
    schemas = [m.model_json_schema() for m in (RunState, EpisodeRunState, TaskState)]
    return hashlib.sha256(json.dumps(schemas, sort_keys=True).encode()).hexdigest()[:16]


def code_stamp() -> CodeStamp:
    """当前代码版本。git 不可用时 commit 记 `unknown`、dirty 记 None——存档不因此失败。"""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, env=env, timeout=10
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        dirty: bool | None = bool(porcelain.stdout.strip()) if porcelain.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        commit, dirty = "", None
    return CodeStamp(
        git_commit=commit or "unknown", git_dirty=dirty, state_schema_hash=state_schema_hash()
    )


def write_manifest(directory: Path, manifest: CheckpointManifest) -> Path:
    """原子写 `<directory>/manifest.json`（临时文件 + 改名），返回路径。

    前置条件：清单引用的世界存档与记忆 zip 都已在盘上。
    """
    assert (directory / manifest.world_file).is_file(), "world.state 还没落盘"
    assert Path(manifest.memory_archive).is_file(), "记忆快照还没落盘"
    path = directory / MANIFEST_FILENAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(manifest.model_dump_json(indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def read_manifest(path: Path) -> CheckpointManifest:
    """读清单并校验产物都在。

    失败：文件不存在 → `CheckpointNotFound`；解析不了或产物缺失 → `CheckpointCorrupt`。
    """
    if not path.is_file():
        raise CheckpointNotFound(f"清单不存在：{path}")
    try:
        manifest = CheckpointManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        raise CheckpointCorrupt(f"清单解析不了：{path}：{exc}") from exc
    if not (path.parent / manifest.world_file).is_file():
        raise CheckpointCorrupt(f"清单引用的世界存档缺失：{path.parent / manifest.world_file}")
    if not Path(manifest.memory_archive).is_file():
        raise CheckpointCorrupt(f"清单引用的记忆快照缺失：{manifest.memory_archive}")
    return manifest


__all__ = [
    "MANIFEST_FILENAME",
    "WORLD_FILENAME",
    "CheckpointManifest",
    "CodeStamp",
    "GraphRef",
    "Level",
    "LineageLink",
    "code_stamp",
    "launch_relative",
    "read_manifest",
    "state_schema_hash",
    "write_manifest",
]
