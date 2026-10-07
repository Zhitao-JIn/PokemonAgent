"""类型化冻结数据集出口。"""

from .loader import load
from .schemas import FrozenRecord, MemoryDataset, Query

__all__ = ["load", "FrozenRecord", "MemoryDataset", "Query"]
