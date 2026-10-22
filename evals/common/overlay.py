"""evals 的配置覆盖文件构造：把 `evals/config.json` 与每条样本的运行时事实翻成 settings 覆盖层。

被测系统（`build_real`）只认 `pokemon_agent/settings/default.json` 加覆盖文件；评测线要改的
只有预算、型号、trace 后端，以及每条样本独有的 run_id / 分支 / 落盘目录 / 服务地址。
这些都写成覆盖 JSON 文件交给 `build_real(config=[…])`，跑完后文件原样留在工作目录里，
"这次评测到底用了什么值"一目了然。
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.runconfig import resolve_models

_LINK_OF_PARAM = {
    "text_model": "text",
    "judge_model": "judge",
    "verify_model": "verify",
    "plan_model": "plan",
}


def eval_overlay(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """`config.json` → settings 覆盖层：预算、四条链路型号、trace 后端。"""
    models = resolve_models(cfg["models"])
    return {
        "budget": dict(cfg["budget"]),
        "trace": {"backend": str(cfg.get("trace_backend", "local"))},
        "models": {_LINK_OF_PARAM[param]: {"model": name} for param, name in models.items()},
    }


def sample_overlay(*, run_id: str, branch: str, work: Path) -> dict[str, Any]:
    """一条样本一个分支的运行时事实：身份、落盘目录、服务地址（取自评测进程环境）。"""
    return {
        "run": {"run_id": run_id, "branch": branch},
        "paths": {
            "runs_root": str(work),
            "trace": "trace",
            "memory": "memory",
            "checkpoint": "checkpoints",
            "config_snapshot": "config_snapshots",
        },
        "services": {
            "world_server_url": os.environ.get("MCP_WORLD_SERVER_URL") or None,
            "memory_server_url": os.environ.get("MCP_MEMORY_SERVER_URL") or None,
        },
    }


def write_overlay(path: Path, overlay: Mapping[str, Any]) -> tuple[Path, str]:
    """落成 JSON 覆盖文件，返回 `(路径, sha256)`。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(dict(overlay), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


__all__ = ["eval_overlay", "sample_overlay", "write_overlay"]
