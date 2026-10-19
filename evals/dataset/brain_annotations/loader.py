"""核验旁账字节、原始输入身份和每条证据后才返回评分参考。"""

import hashlib
import json
from pathlib import Path

from evals.dataset.brain_calls import load_inputs
from evals.dataset.brain_calls.loader import directory_for
from evals.dataset.errors import DatasetError
from evals.dataset.io import read_models, version_directory

from .contract import Annotation
from .evidence import encoded, resolve

ROOT = Path(__file__).resolve().parent


def load(family: str, version: str = "v1") -> list[Annotation]:
    """任一哈希、数量、身份或证据失配抛 DatasetError；未评分项也必须完整核验。"""
    directory = version_directory(ROOT, version)
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    if manifest["version"] != version or family not in manifest["families"]:
        raise DatasetError("annotation family/version mismatch")
    expected = manifest["families"][family]
    path = directory / f"{family}.jsonl"
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
        raise DatasetError("annotation file hash mismatch")
    _, source = directory_for(family, manifest["collection_version"])
    if source.files_sha256["inputs.jsonl"] != expected["inputs_sha256"]:
        raise DatasetError("annotation source hash mismatch")
    rows = read_models(path, Annotation)
    cases = load_inputs(family, manifest["collection_version"])
    if len(rows) != expected["cases"] or [row.case_id for row in rows] != [
        c.case_id for c in cases
    ]:
        raise DatasetError("annotation identity/count mismatch")
    for case, row in zip(cases, rows, strict=True):
        if row.family != family or row.request_sha256 != case.source.request_canonical_sha256:
            raise DatasetError("annotation request mismatch")
        request = case.request.model_dump(mode="json")
        for evidence in row.evidence:
            value = encoded(resolve(request, evidence.pointer))
            if (
                hashlib.sha256(value.encode()).hexdigest() != evidence.sha256
                or value[:1200] != evidence.excerpt
            ):
                raise DatasetError("annotation evidence mismatch")
    return rows
