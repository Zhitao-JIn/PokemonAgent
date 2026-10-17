"""评测共用：清空共享 memory server 的库（以空 zip 还原，全删）。"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from pokemon_agent.mcpclient.memory_local import MemoryTool
from pokemon_agent.schemas.harness import FromHarnessToMemoryToolRestoreMemoryReq


def clear_memory(tool: MemoryTool) -> None:
    """写一个空 zip 并还原，清空整个记忆库。

    前置条件：server 带 --enable-admin（否则 restore 被拒，错误向上传递）。
    后置条件：之后任一 recall 无记录。
    """
    with tempfile.TemporaryDirectory(prefix="clear-memory-") as directory:
        archive = Path(directory) / "empty.zip"
        with zipfile.ZipFile(archive, "w"):
            pass
        tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=str(archive)))


__all__ = ["clear_memory"]
