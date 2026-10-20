"""逐例作者表：一行一个 case_id，构建器要求与冻结原料逐例对应。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models

ROOT = Path(__file__).resolve().parent / "authoring"


class Authored(BaseModel):
    """作者对一个现场的裁定；排除项不携带答案。"""

    model_config = ConfigDict(extra="forbid")
    case_id: str
    status: Literal["labelled", "invalid_task", "unjudgeable"]
    rationale: str = Field(min_length=1)
    suggestions: list[str] = Field(default_factory=list)
    achieved: bool | None = None
    expected_decision: Literal["achieved", "continue", "blocked", "interrupted"] | None = None


def load_authoring(version: str, family: str, case_ids: list[str]) -> dict[str, Authored]:
    """缺登记、多登记、重复或排除项携带答案均抛 DatasetError；路径不存在时同样失败。"""
    path = ROOT / version / f"{family}.jsonl"
    if not path.is_file():
        raise DatasetError(f"authoring table missing: {path}")
    rows = read_models(path, Authored)
    by_id = {row.case_id: row for row in rows}
    if len(by_id) != len(rows):
        raise DatasetError("authoring table has duplicate case_id")
    if set(by_id) - set(case_ids):
        raise DatasetError("authoring table has unknown case_id")
    missing = [i for i in case_ids if i not in by_id and not mechanical_ok(family)]
    if missing:
        raise DatasetError(f"authoring table misses {len(missing)} cases, first {missing[0]}")
    for row in rows:
        if row.status != "labelled" and (row.achieved is not None or row.expected_decision):
            raise DatasetError("excluded authoring row carries an answer")
        if family == "judge" and row.status == "labelled" and row.achieved is None:
            raise DatasetError(f"judge authoring row lacks achieved: {row.case_id}")
    return by_id


def mechanical_ok(family: str) -> bool:
    """judge 的机械标签例不要求登记；其余家族逐例必须登记。"""
    return family == "judge"
