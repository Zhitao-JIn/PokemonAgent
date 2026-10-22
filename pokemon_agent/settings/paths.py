"""路径解析与生效配置快照落盘：配置里的相对路径一律按**仓库根**解析，不跟启动目录走。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .schema import PathsSection, ResolvedConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
"""仓库根：本文件的上上上级目录（与 `env.py` 找 `.env` 的口径一致）。"""

PathName = Literal["trace", "memory", "checkpoint", "config_snapshot"]


def resolve_path(paths: PathsSection, name: PathName) -> Path:
    """某个落盘目录的绝对路径。

    `runs_root` 是基准；相对的 `runs_root` 按仓库根解析，相对的子项按 `runs_root` 解析，
    绝对路径原样使用。不创建目录——创建是各自 tool 的事。
    """
    root = Path(paths.runs_root)
    if not root.is_absolute():
        root = REPO_ROOT / root
    sub = Path(getattr(paths, name))
    return sub if sub.is_absolute() else root / sub


def write_snapshot(resolved: ResolvedConfig, directory: Path, run_id: str) -> Path:
    """把生效配置连同来源与摘要写成一个 JSON 文件，返回文件路径。

    文件名 `<run_id>-<sha256 前 8 位>.json`；同一 run 同一份配置重复写是幂等的覆盖。
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{run_id}-{resolved.sha256[:8]}.json"
    payload = {
        "run_id": run_id,
        "sources": list(resolved.sources),
        "sha256": resolved.sha256,
        "config": json.loads(resolved.merged_json),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
