"""采集控制协议与原子状态；不保存密钥或进程环境。"""

import os
from pathlib import Path
from time import time

from pydantic import BaseModel, Field


class ControlState(BaseModel):
    """批次状态；所有变更由持有 token 的单一 worker 写入。"""

    token: str
    pid: int = 0
    phase: str = "preflight"
    status: str = "starting"
    completed: list[str] = Field(default_factory=list)
    sample_ids: list[str] | None = None
    current_sample: str | None = None
    error: str = ""
    updated_at: float = Field(default_factory=time)
    attempts: dict[str, int] = Field(default_factory=dict)
    output: str | None = None


def save_state(directory: Path, state: ControlState) -> None:
    """同目录临时文件后原子替换；冲突只可能来自控制器违约。"""
    state.updated_at = time()
    target = directory / "control.json"
    temporary = directory / f"control.{state.token}.tmp"
    temporary.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, target)


def read_state(directory: Path) -> ControlState:
    """读取当前完整快照；缺失或损坏显式失败。"""
    return ControlState.model_validate_json((directory / "control.json").read_text("utf-8"))
