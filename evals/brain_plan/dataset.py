"""plan 冻结现场：输入和独立参考分离，不复制或改写原始录制。"""

from pathlib import Path

from pydantic import BaseModel

from evals.common.capability_dataset import load_capability
from evals.dataset.brain_calls.dataset_contract import ReferenceCase
from evals.paths import REPO_ROOT
from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq

DATASET_DIR: Path = REPO_ROOT / "evals/dataset/brain_plan"


class Case(BaseModel):
    """一个 plan 用例；reference 只供评分，不能进入生产请求。"""

    case_id: str
    request: FromHarnessToBrainToolPlanOnceReq
    reference: ReferenceCase


def load(version: str = "v1") -> list[Case]:
    """按原冻结顺序加载；类型、字节哈希或配对异常显式失败。"""
    data = load_capability(DATASET_DIR, "plan", version)
    return [
        Case(case_id=row.case_id, request=row.request, reference=reference)
        for row, reference in zip(data.inputs, data.references, strict=True)
    ]
