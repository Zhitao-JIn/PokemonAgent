"""读取106条统一脚本用例；冻结文件与存档自包含。"""

from pathlib import Path

from evals.dataset.errors import DatasetError
from evals.dataset.io import contained_file, read_models, version_directory

from .schemas import ScriptCase

DATASET_DIR = Path(__file__).resolve().parent
DEFAULT_VERSION = "v1"


def state_path(state: str, version: str = DEFAULT_VERSION) -> Path:
    """解析本版本 states 下的存档；越界或缺失抛 DatasetError。"""
    return contained_file(version_directory(DATASET_DIR, version) / "states", state)


def load(version: str = DEFAULT_VERSION) -> list[ScriptCase]:
    """返回顺序不变的脚本样本；重复id或引用无效抛 DatasetError。"""
    cases = read_models(version_directory(DATASET_DIR, version) / "cases.jsonl", ScriptCase)
    if len({case.case_id for case in cases}) != len(cases):
        raise DatasetError("脚本 case_id 重复")
    for case in cases:
        state_path(case.state, version)
        if version != "v1" and case.kind is None:
            raise DatasetError(f"{version} 用例 {case.case_id} 缺少 kind")
    if version == "v1":
        cases = [
            case.model_copy(update={"kind": "success" if case.expect.ok else "failure"})
            if case.kind is None
            else case
            for case in cases
        ]
    return cases
