"""checkpointer 的错误词汇（模块自治：自有根类型，不继承全局 `AgentError`）。"""

from __future__ import annotations


class CheckpointError(Exception):
    """checkpointer 一切预期内失败的根。"""


class CheckpointNotFound(CheckpointError):
    """要恢复的存档不存在（清单文件找不到）。"""


class CheckpointCorrupt(CheckpointError):
    """清单读得到但解析不了，或它引用的产物缺失。"""


class CheckpointIncompatible(CheckpointError):
    """存档与当前代码的状态结构不兼容（`state_schema_hash` 不同），拒绝加载。"""


__all__ = [
    "CheckpointCorrupt",
    "CheckpointError",
    "CheckpointIncompatible",
    "CheckpointNotFound",
]
