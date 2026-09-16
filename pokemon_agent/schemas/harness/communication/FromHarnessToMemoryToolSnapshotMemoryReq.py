"""`FromHarnessToMemoryToolSnapshotMemoryReq`：harness → `MemoryTool` 的记忆快照请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolSnapshotMemoryReq(BaseModel):
    """**给这张快照起个名**（0916）——zip 落到哪由 memory 层决定，harness 不管。

    此前那套"归档"（`archive_many` 把记录搬进 `memory/voided-<ts>/<kind>/`）已删，
    换成一个能整体还原的 zip 快照：`snapshot_memory` 打、`restore_memory` 以它为准还原回来。

    只有 `name` 这一个字段，因为剩下的都是 memory 自己的事——快照放哪个目录、
    叫什么后缀、要不要给每族单独打包，都归它（`memory/store.py` 的
    `SNAPSHOTS_DIRNAME`）。**harness 只需要能说"这次拍个名叫 X 的"**。
    """

    name: str = Field(description="快照名（文件名，不含路径分隔符）；同名覆盖")


__all__ = ["FromHarnessToMemoryToolSnapshotMemoryReq"]
