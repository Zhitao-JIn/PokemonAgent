"""读取并核验版本化的目标判定冻结样本。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from evals.dataset.errors import DatasetError
from evals.dataset.io import contained_file, read_models, version_directory

from .schemas import JudgeCaseV1, JudgeCaseV2
from .schemas_v3 import JudgeCaseV3

DATASET_DIR = Path(__file__).resolve().parent
DEFAULT_VERSION = "v1"
_VERSION_MODELS: dict[str, type[JudgeCaseV1] | type[JudgeCaseV2]] = {
    "v1": JudgeCaseV1,
    "v2": JudgeCaseV2,
    "v3": JudgeCaseV3,
}
_LoadedCase: TypeAlias = JudgeCaseV1 | JudgeCaseV2 | JudgeCaseV3


class _DatasetManifest(BaseModel):
    """冻结数据文件及其版本内 SHA-256。"""

    model_config = ConfigDict(extra="forbid")

    version: str
    dataset_file: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def load(version: str = DEFAULT_VERSION) -> list[_LoadedCase]:
    """按版本读取冻结样本；版本、清单、哈希或样本契约错误抛 DatasetError。"""
    if version not in _VERSION_MODELS:
        raise DatasetError(f"不支持的数据集版本：{version!r}")
    directory = version_directory(DATASET_DIR, version)
    manifests = read_models(directory / "manifest.json", _DatasetManifest, json_lines=False)
    if len(manifests) != 1:
        raise DatasetError(f"{version}/manifest.json 必须恰有一条清单")
    manifest = manifests[0]
    if manifest.version != version:
        raise DatasetError(f"清单版本 {manifest.version!r} 与请求版本 {version!r} 不一致")
    dataset_path = contained_file(directory, manifest.dataset_file)
    actual_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if actual_sha256 != manifest.dataset_sha256:
        raise DatasetError(f"冻结数据哈希不符：{manifest.dataset_file}")
    rows = read_models(dataset_path, _VERSION_MODELS[version], json_lines=True)
    if len({row.case_id for row in rows}) != len(rows):
        raise DatasetError("judge case_id 重复")
    return rows


__all__ = ["load"]
