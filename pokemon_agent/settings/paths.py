"""路径解析与生效配置快照落盘：配置里的相对路径一律按**仓库根**解析，不跟启动目录走。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
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


def write_snapshot(
    resolved: ResolvedConfig,
    directory: Path,
    run_id: str,
    prompts: Mapping[str, Mapping[str, str]],
) -> Path:
    """把生效配置连同来源与摘要写成一个 JSON 文件，返回文件路径。

    `sha256` 覆盖规范化配置与提示词版本清单；同一输入重复写是幂等覆盖。
    """
    prompt_data = {
        name: {"version": prompts[name]["version"], "hash": prompts[name]["hash"]}
        for name in sorted(prompts)
    }
    config_data = json.loads(resolved.merged_json)
    identity = json.dumps(
        {"config": config_data, "prompts": prompt_data},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    snapshot_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{run_id}-{snapshot_hash[:8]}.json"
    payload = {
        "run_id": run_id,
        "sources": list(resolved.sources),
        "sha256": snapshot_hash,
        "config": config_data,
        "prompts": prompt_data,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
