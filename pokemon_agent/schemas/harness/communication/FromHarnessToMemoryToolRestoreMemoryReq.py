"""`FromHarnessToMemoryToolRestoreMemoryReq`：harness → `MemoryTool` 的记忆恢复请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolRestoreMemoryReq(BaseModel):
    """**用哪个 zip 还原回来**（0916）——给路径，不给名字。

    与 `snapshot` 那侧不对称是有意的：拍快照只要一个名字（放哪归 memory 决定），
    而恢复**必须**能接受任意路径——"拿别人给的、或更早的一份 zip 灌回来"正是
    "覆盖读取"的价值所在，把路径也收进 memory 的自管目录就等于把这条路堵死了。

    以 zip 为准：zip 里有的记录按 zip 写（同名直接盖），**zip 里没有的记录文件
    从库里删掉**——恢复的语义单位是**整个库**，不是"往库上叠一层"。
    """

    archive: str = Field(description="要恢复的 zip 路径（盘上存在的文件）")


__all__ = ["FromHarnessToMemoryToolRestoreMemoryReq"]
