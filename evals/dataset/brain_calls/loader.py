"""分别加载完整生产输入与评分参考，模型调用方无需接触真值。"""

import hashlib
from pathlib import Path

from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models, version_directory

from .dataset_contract import DatasetManifest, Family, InputCase, ReferenceCase

DATASET_DIR = Path(__file__).resolve().parent


def directory_for(family: Family, version: str) -> tuple[Path, DatasetManifest]:
    """核对家族清单与所有字节指纹；版本或文件异常显式失败。"""
    directory = version_directory(DATASET_DIR, version) / family
    manifest = DatasetManifest.model_validate_json((directory / "manifest.json").read_text("utf-8"))
    if manifest.family != family or manifest.version != version:
        raise DatasetError("brain call family/version mismatch")
    for name, expected in manifest.files_sha256.items():
        if Path(name).name != name:
            raise DatasetError("manifest file must be a local name")
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise DatasetError(f"brain call data hash mismatch: {name}")
    return directory, manifest


def load_inputs(family: Family, version: str = "v1") -> list[InputCase]:
    """返回原始生产请求；标签和旧答案均不返回。"""
    directory, manifest = directory_for(family, version)
    rows = read_models(directory / "inputs.jsonl", InputCase)
    if len(rows) != manifest.cases or len({row.case_id for row in rows}) != len(rows):
        raise DatasetError("brain call input count/identity mismatch")
    return rows


def load_references(family: Family, version: str = "v1") -> list[ReferenceCase]:
    """仅供评分方读取独立参考；缺标签不得计入已标注指标分母。"""
    directory, manifest = directory_for(family, version)
    rows = read_models(directory / "references.jsonl", ReferenceCase)
    if len(rows) != manifest.cases or len({row.case_id for row in rows}) != len(rows):
        raise DatasetError("brain call reference count/identity mismatch")
    return rows
