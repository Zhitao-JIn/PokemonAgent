"""验证五类数据的字节、请求类型、来源、评分配对与禁止答案泄漏边界。"""

import argparse
import hashlib
import json
from pathlib import Path

from evals.dataset.brain_choose.schemas import ActionMatcher
from evals.paths import REPO_ROOT

from .dataset_contract import DatasetManifest, InputCase, ReferenceCase
from .source_archive import verify_sources


def canonical_digest(value: object) -> str:
    """结构化请求哈希，不依赖空白和换行。"""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_pair(
    row: InputCase,
    ref: ReferenceCase,
    sources: dict[str, bytes] | None,
    raw_request: dict,
) -> None:
    """来源字节、完整请求、标签类型各自核验。"""
    source = (
        sources[row.source.request_file]
        if sources is not None
        else (REPO_ROOT / row.source.request_file).read_bytes()
    )
    if hashlib.sha256(source).hexdigest() != row.source.request_sha256:
        raise ValueError("original request changed")
    original = json.loads(source)
    exported = raw_request
    if canonical_digest(exported) != row.source.request_canonical_sha256:
        raise ValueError("typed input round trip changed request")
    if original != exported:
        raise ValueError("exported input differs from actual production request")
    typed_source = InputCase.model_validate({**row.model_dump(mode="json"), "request": original})
    if typed_source.request.model_dump(mode="json") != row.request.model_dump(mode="json"):
        raise ValueError("typed input round trip changed request")
    if ref.evaluation == "mechanical" and (
        ref.achieved is None or not ref.check_id or ref.label_source != "mechanical"
    ):
        raise ValueError("invalid mechanical gold")
    if ref.evaluation != "mechanical" and ref.achieved is not None:
        raise ValueError("rubric must not masquerade as binary gold")


def verify_labels(row: InputCase, ref: ReferenceCase) -> None:
    """确定性动作集合必须非空、类型正确且逐项属于原能力掩码。"""
    if ref.evaluation != "action_set":
        return
    if row.family != "choose" or ref.label_source != "mechanical" or not ref.check_id:
        raise ValueError("action labels have invalid family/source")
    actions = [ActionMatcher.model_validate(value) for value in ref.constraints["acceptable"]]
    if not actions or any(
        not row.request.space.enabled(action.key or action.script) for action in actions
    ):
        raise ValueError("action labels outside the original action space")


def verify(root: Path) -> dict[str, int]:
    """缺文件、哈希漂移、请求重读漂移、引用错配或评分混用均显式失败。"""
    counts = {}
    sources = verify_sources(root) if (root / "sources.manifest.json").exists() else None
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        manifest = DatasetManifest.model_validate_json(
            (directory / "manifest.json").read_text("utf-8")
        )
        for name, expected in manifest.files_sha256.items():
            actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"dataset file hash mismatch: {directory / name}")
        inputs = [
            InputCase.model_validate_json(line)
            for line in (directory / "inputs.jsonl").read_text("utf-8").splitlines()
        ]
        refs = [
            ReferenceCase.model_validate_json(line)
            for line in (directory / "references.jsonl").read_text("utf-8").splitlines()
        ]
        if len(inputs) != manifest.cases or len(refs) != manifest.cases:
            raise ValueError("case count mismatch")
        if [row.case_id for row in inputs] != [ref.case_id for ref in refs]:
            raise ValueError("input/reference pairing mismatch")
        if len({row.case_id for row in inputs}) != len(inputs):
            raise ValueError("duplicate case id")
        raw_requests = {
            item["case_id"]: item["request"]
            for item in (
                json.loads(line)
                for line in (directory / "inputs.jsonl").read_text("utf-8").splitlines()
            )
        }
        for row, ref in zip(inputs, refs, strict=True):
            verify_pair(row, ref, sources, raw_requests[row.case_id])
            verify_labels(row, ref)
        if manifest.action_set_labels != sum(ref.evaluation == "action_set" for ref in refs):
            raise ValueError("action label count mismatch")
        if manifest.mechanical_labels != sum(ref.achieved is not None for ref in refs):
            raise ValueError("binary label count mismatch")
        counts[manifest.family] = len(inputs)
    if set(counts) != {"judge", "plan", "decompose", "choose", "summary"}:
        raise ValueError("missing family")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.root), ensure_ascii=True))
