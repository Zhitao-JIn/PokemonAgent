"""独立能力数据集清单；复用审计原料但独立固定版本和输入/参考指纹。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.dataset.brain_calls import load_inputs, load_references
from evals.dataset.brain_calls.dataset_contract import InputCase, ReferenceCase
from evals.dataset.brain_calls.loader import directory_for
from evals.dataset.errors import DatasetError
from evals.dataset.io import version_directory


class CapabilityManifest(BaseModel):
    """单个能力的发布清单，不能悄悄切换到另一能力或另一批原料。"""

    model_config = ConfigDict(extra="forbid")
    version: str
    family: Literal["plan", "decompose"]
    collection_version: str
    cases: int = Field(gt=0)
    inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    references_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CapabilityData(BaseModel):
    """独立发布版本选定的完整输入与评分参考。"""

    inputs: list[InputCase]
    references: list[ReferenceCase]


def load_capability(directory: Path, family: str, version: str) -> CapabilityData:
    """清单不匹配抛 DatasetError；源文件、JSON 或类型异常原样透传。"""
    manifest = CapabilityManifest.model_validate_json(
        (version_directory(directory, version) / "manifest.json").read_text("utf-8")
    )
    if manifest.family != family or manifest.version != version:
        raise DatasetError("capability/version mismatch")
    _, source = directory_for(manifest.family, manifest.collection_version)
    if (
        source.files_sha256["inputs.jsonl"] != manifest.inputs_sha256
        or source.files_sha256["references.jsonl"] != manifest.references_sha256
        or source.cases != manifest.cases
    ):
        raise DatasetError("capability source fingerprint mismatch")
    inputs = load_inputs(manifest.family, manifest.collection_version)
    references = load_references(manifest.family, manifest.collection_version)
    if [row.case_id for row in inputs] != [row.case_id for row in references]:
        raise DatasetError("capability input/reference pairing mismatch")
    return CapabilityData(inputs=inputs, references=references)
