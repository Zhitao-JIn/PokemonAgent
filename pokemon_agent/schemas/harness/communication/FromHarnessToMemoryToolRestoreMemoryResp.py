"""`FromHarnessToMemoryToolRestoreMemoryResp`：harness → `MemoryTool` 的记忆恢复响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolRestoreMemoryResp(BaseModel):
    """**这次还原解出了几个文件**（0916）。

    记条数是为了让调用方分得清两种"看起来没变化"：`unpacked=0` 是那份 zip
    里没有本层认的记录（空快照、或路径形状对不上——`restore` 会跳过它们）；
    `unpacked>0` 但库看着没变，多半是还原回了同一批内容。两者在日志里必须不同。
    """

    unpacked: int = Field(description="解出的记录文件数")


__all__ = ["FromHarnessToMemoryToolRestoreMemoryResp"]
