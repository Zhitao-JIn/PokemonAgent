"""choose 建议式现场；完整请求和只供 AI 评分的参考隔离。"""

from pathlib import Path

from pydantic import BaseModel

from evals.common.capability_dataset import load_capability
from evals.dataset.brain_calls.dataset_contract import ReferenceCase
from evals.paths import REPO_ROOT
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq

DATASET_DIR: Path = REPO_ROOT / "evals/dataset/brain_choose"


class Case(BaseModel):
    """建议动作不进入生产 chooser；评分可接受未列入建议的合法替代。"""

    case_id: str
    request: FromHarnessToBrainToolChooseOnceReq
    reference: ReferenceCase


def load(version: str = "v20261020_1846") -> list[Case]:
    """哈希、输入/旁账配对或证据不匹配显式失败，排除项不进入运行分母。"""
    data = load_capability(DATASET_DIR, "choose", version)
    return [
        Case(case_id=case.case_id, request=case.request, reference=reference)
        for case, reference in zip(data.inputs, data.references, strict=True)
    ]
