"""复用冻结原料，独立冻结 rubric；不读取 baseline 响应作为标签。"""

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field

from evals.dataset.brain_calls import load_inputs
from evals.dataset.brain_calls.dataset_contract import REQUESTS, Criterion, InputCase, ReferenceCase
from evals.dataset.brain_calls.loader import directory_for
from evals.dataset.errors import DatasetError
from evals.dataset.io import version_directory
from evals.paths import REPO_ROOT

from .contract import DIMENSIONS, Layer, SummaryRequest

ROOT: Path = REPO_ROOT / "evals/dataset/brain_summary"
DEFAULT_VERSION = "v20261020_1846"


class Manifest(BaseModel):
    """发布输入和量表的字节指纹；不携带参考答案。"""

    version: str
    collection_version: str
    cases: int
    layers: dict[Layer, int]
    inputs_sha256: str
    rubric_sha256: str


class Rubric(BaseModel):
    """五个固定维度及逐层说明，作为独立评分依据。"""

    criteria: list[Criterion] = Field(min_length=1)
    layer_guidance: dict[Layer, str]


class Case(BaseModel):
    """仅 request 传给生产门面；reference 只供评分员。"""

    case_id: str
    layer: Layer
    request: SummaryRequest
    reference: ReferenceCase


def load(version: str = DEFAULT_VERSION) -> list[Case]:
    """身份、字节、请求层级或量表错配均失败，不静默跳过。"""
    directory = version_directory(ROOT, version)
    manifest = Manifest.model_validate_json((directory / "manifest.json").read_text("utf-8"))
    rubric_bytes = (directory / "rubric.json").read_bytes()
    _, source = directory_for("summary", manifest.collection_version)
    if manifest.version != version or (
        hashlib.sha256(rubric_bytes).hexdigest() != manifest.rubric_sha256
        or source.files_sha256["inputs.jsonl"] != manifest.inputs_sha256
        or source.cases != manifest.cases
        or source.layers != manifest.layers
    ):
        raise DatasetError("summary manifest/source mismatch")
    rubric = Rubric.model_validate_json(rubric_bytes)
    if [item.name for item in rubric.criteria] != list(DIMENSIONS):
        raise DatasetError("summary rubric dimensions mismatch")
    return [make_case(row, rubric) for row in load_inputs("summary", manifest.collection_version)]


def make_case(row: InputCase, rubric: Rubric) -> Case:
    """按冻结 method/layer 验证精确信封；不接受旧契约或相似字段猜测。"""
    methods = {"task": "summarize_task", "episode": "summarize", "run": "summarize_run"}
    if (
        row.contract_version != "v2"
        or row.method != methods[row.layer]
        or not isinstance(row.request, REQUESTS[row.method])
    ):
        raise DatasetError("summary requires an exact v2 request matching its layer")
    return Case(
        case_id=row.case_id,
        layer=row.layer,
        request=row.request,
        reference=ReferenceCase(
            case_id=row.case_id,
            evaluation="source_grounded_rubric",
            criteria=[item.model_copy(deep=True) for item in rubric.criteria],
            constraints={"layer_guidance": rubric.layer_guidance[row.layer]},
            evidence=[],
        ),
    )
