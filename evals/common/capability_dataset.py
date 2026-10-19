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
    annotation_version: str | None = None
    annotation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


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
    data = CapabilityData(inputs=inputs, references=references)
    return reviewed_data(data, manifest) if manifest.annotation_version else data


def reviewed_data(data: CapabilityData, manifest: CapabilityManifest) -> CapabilityData:
    """固定旁账指纹并排除无效/无从判项；保留原输入对象，参考仅供评分。"""
    import hashlib

    from evals.dataset.brain_annotations.loader import ROOT, load
    from evals.dataset.brain_annotations.references import combine

    assert manifest.annotation_version is not None
    path = version_directory(ROOT, manifest.annotation_version) / f"{manifest.family}.jsonl"
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.annotation_sha256:
        raise DatasetError("capability annotation hash mismatch")
    annotations = load(manifest.family, manifest.annotation_version)
    if [row.case_id for row in data.inputs] != [row.case_id for row in annotations]:
        raise DatasetError("capability annotation pairing mismatch")
    pairs = [
        (case, combine(ref, annotation))
        for case, ref, annotation in zip(data.inputs, data.references, annotations, strict=True)
        if annotation.status == "labelled"
    ]
    return CapabilityData(inputs=[case for case, _ in pairs], references=[ref for _, ref in pairs])
