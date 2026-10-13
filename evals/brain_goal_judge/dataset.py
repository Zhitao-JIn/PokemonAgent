"""读取brain_goal_judge的冻结样本。"""

from pathlib import Path

from pydantic import BaseModel

from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models, version_directory
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq


class JudgeCase(BaseModel):
    """标签不会传给判定器，只由 scorer 消费。"""

    case_id: str
    request: FromHarnessToBrainToolJudgeReq
    achieved: bool


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


__all__ = ["JudgeCase", "load"]
