"""分支登记表 `<存档根>/<run_id>/branches.json`：每条执行线从哪来（checkpoint SPEC §三）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from .manifest import LineageLink

BRANCHES_FILENAME = "branches.json"


class BranchRecord(BaseModel):
    """一条恢复出来的执行线：它的父线、来源存档与完整血缘（由根到父）。"""

    branch: str
    parent: str
    checkpoint_id: str
    lineage: list[LineageLink]
    created_at: str


_TABLE = TypeAdapter(dict[str, BranchRecord])


def read_branches(run_dir: Path) -> dict[str, BranchRecord]:
    """读登记表；还没有恢复过时为空。"""
    path = run_dir / BRANCHES_FILENAME
    if not path.is_file():
        return {}
    return _TABLE.validate_json(path.read_text(encoding="utf-8"))


def register_branch(run_dir: Path, *, parent: str, lineage: list[LineageLink]) -> BranchRecord:
    """登记一条新执行线，名字取 `b<n>`（n 为已登记条数 + 1），原子写回。

    前置条件：`lineage` 非空，最后一环就是父线（`lineage[-1].branch == parent`）。
    后置条件：返回的名字此前未登记过。
    """
    assert lineage and lineage[-1].branch == parent, "血缘的最后一环必须是父线"
    table = read_branches(run_dir)
    name = f"b{len(table) + 1}"
    assert name not in table and name != "main"
    record = BranchRecord(
        branch=name,
        parent=parent,
        checkpoint_id=lineage[-1].checkpoint_id,
        lineage=lineage,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    table[name] = record
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / (BRANCHES_FILENAME + ".tmp")
    tmp.write_text(
        json.dumps({k: v.model_dump() for k, v in table.items()}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    tmp.replace(run_dir / BRANCHES_FILENAME)
    return record


__all__ = ["BRANCHES_FILENAME", "BranchRecord", "read_branches", "register_branch"]
