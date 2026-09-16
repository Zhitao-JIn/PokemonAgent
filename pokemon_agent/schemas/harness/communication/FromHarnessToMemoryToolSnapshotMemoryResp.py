"""`FromHarnessToMemoryToolSnapshotMemoryResp`：harness → `MemoryTool` 的记忆快照响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolSnapshotMemoryResp(BaseModel):
    """**快照 zip 落在哪**（0916）——一个盘上真实存在的路径。

    调用方拿到它才能把"这份存档在哪"记下来（日志、指针文件、下一次 restore）。
    """

    archive: str = Field(description="快照 zip 的完整路径（盘上已存在）")


__all__ = ["FromHarnessToMemoryToolSnapshotMemoryResp"]
