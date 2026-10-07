"""读取brain_goal_judge的冻结样本。"""

from pathlib import Path

from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models, version_directory

from .schemas import JudgeCase

DATASET_DIR = Path(__file__).resolve().parent
DEFAULT_VERSION = "v1"


def load(version: str = DEFAULT_VERSION) -> list[JudgeCase]:
    """返回类型化样本；冻结文件或契约错误抛 DatasetError。"""
    rows = read_models(
        version_directory(DATASET_DIR, version) / "dataset.jsonl", JudgeCase, json_lines=True
    )
    if len({c.case_id for c in rows}) != len(rows):
        raise DatasetError("judge case_id 重复")
    return rows
