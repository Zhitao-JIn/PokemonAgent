"""读取memory_store_recall的冻结样本。"""

from pathlib import Path

from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models, version_directory

from .schemas import MemoryDataset

DATASET_DIR = Path(__file__).resolve().parent
DEFAULT_VERSION = "v1"


def load(version: str = DEFAULT_VERSION) -> list[MemoryDataset]:
    """返回类型化样本；冻结文件或契约错误抛 DatasetError。"""
    rows = read_models(
        version_directory(DATASET_DIR, version) / "dataset.json", MemoryDataset, json_lines=False
    )
    for dataset in rows:
        identities = {entry.record_id for entry in dataset.records}
        if len(identities) != len(dataset.records):
            raise DatasetError("record_id 不唯一")
        if not all(set(q.relevant) <= identities for q in dataset.queries):
            raise DatasetError("相关性标注引用未知记录")
    return rows
