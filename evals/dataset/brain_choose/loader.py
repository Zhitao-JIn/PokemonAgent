"""读取冻结的版本化单步现场，保留原始 choose 请求与完整任务历史。"""

from pathlib import Path

from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models, version_directory

from .schemas import ChooseCase

DATASET_DIR = Path(__file__).resolve().parent


def load(version: str = "v1") -> list[ChooseCase]:
    """按文件顺序读取；版本、文件、格式错误或重复 case_id 均抛 DatasetError。"""
    cases = read_models(version_directory(DATASET_DIR, version) / "cases.jsonl", ChooseCase)
    if len({case.case_id for case in cases}) != len(cases):
        raise DatasetError("brain_choose 的 case_id 重复")
    return cases
