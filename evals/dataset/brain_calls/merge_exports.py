"""把同一采集的多段已核验导出并成一个集合；逐段登记提交，不重新导出批次。"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from evals.agent_short_goal_run.dataset.loader import load_samples

from .dataset_contract import DatasetManifest, InputCase, ReferenceCase, SourcePart
from .source_archive import SourceArchiveManifest
from .verify_dataset import verify

FAMILIES = ("judge", "plan", "decompose", "choose", "summary")


def digest(path: Path) -> str:
    """文件字节哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_lines(path: Path) -> list[str]:
    """按行原样读取，不重新序列化，保持各段字节。"""
    return [line for line in path.read_text("utf-8").splitlines() if line.strip()]


def merge_family(
    parts: list[Path], family: str, order: dict[str, int], out: Path, version: str
) -> tuple[list[tuple[InputCase, ReferenceCase]], list[DatasetManifest], Path, list[Path]]:
    """按样本名升序合并一族；重复 case_id、schema 不一致、输入参考错位均失败。"""
    rows: list[tuple[int, int, str, str, str]] = []
    manifests: list[DatasetManifest] = []
    schemas: dict[str, bytes] = {}
    for part_index, part in enumerate(parts):
        manifests.append(
            DatasetManifest.model_validate_json(
                (part / family / "manifest.json").read_text("utf-8")
            )
        )
        inputs = read_lines(part / family / "inputs.jsonl")
        refs = read_lines(part / family / "references.jsonl")
        if len(inputs) != len(refs):
            raise ValueError(f"{family}: input/reference count mismatch in {part}")
        for position, (left, right) in enumerate(zip(inputs, refs, strict=True)):
            case = InputCase.model_validate_json(left)
            ref = ReferenceCase.model_validate_json(right)
            if case.case_id != ref.case_id:
                raise ValueError(f"{family}: pairing mismatch at {case.case_id}")
            rows.append(
                (
                    order[case.source.sample_id],
                    part_index * 10**6 + position,
                    left,
                    right,
                    case.case_id,
                )
            )
        for schema in (part / family).glob("*.request.schema.json"):
            data = schema.read_bytes()
            if schemas.setdefault(schema.name, data) != data:
                raise ValueError(f"{family}: request schema differs between parts: {schema.name}")
    rows.sort(key=lambda item: (item[0], item[1]))
    ids = [item[4] for item in rows]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{family}: duplicate case_id across parts")
    directory = out / family
    directory.mkdir(parents=True, exist_ok=False)
    files = []
    for name, index in (("inputs.jsonl", 2), ("references.jsonl", 3)):
        path = directory / name
        path.write_text("".join(item[index] + "\n" for item in rows), "utf-8", newline="\n")
        files.append(path)
    for name, data in sorted(schemas.items()):
        path = directory / name
        path.write_bytes(data)
        files.append(path)
    pairs = [
        (InputCase.model_validate_json(item[2]), ReferenceCase.model_validate_json(item[3]))
        for item in rows
    ]
    return pairs, manifests, directory, files


def merge_sources(parts: list[Path], out: Path) -> SourceArchiveManifest:
    """来源包条目取并集；同名不同字节说明两段不是同一集合，直接失败。"""
    entries: dict[str, str] = {}
    blobs: dict[str, bytes] = {}
    for part in parts:
        manifest = SourceArchiveManifest.model_validate_json(
            (part / "sources.manifest.json").read_text("utf-8")
        )
        if digest(part / manifest.archive) != manifest.archive_sha256:
            raise ValueError(f"source archive hash mismatch: {part}")
        with ZipFile(part / manifest.archive) as stream:
            for name, sha in manifest.entries.items():
                data = stream.read(name)
                if hashlib.sha256(data).hexdigest() != sha:
                    raise ValueError(f"source entry hash mismatch: {name}")
                if entries.setdefault(name, sha) != sha:
                    raise ValueError(f"source entry conflicts between parts: {name}")
                blobs[name] = data
    archive = out / "sources.zip"
    with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=9) as stream:
        for name in sorted(blobs):
            info = ZipInfo(name, date_time=(2026, 10, 19, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            stream.writestr(info, blobs[name], compresslevel=9)
    manifest = SourceArchiveManifest(
        archive=archive.name, archive_sha256=digest(archive), entries=dict(sorted(entries.items()))
    )
    (out / "sources.manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def merge(parts: list[Path], output: Path, version: str) -> dict[str, int]:
    """输出目录必须不存在；合并后覆盖全部数据集样本，并通过整体 verify。"""
    samples = sorted(sample.sample_id for sample in load_samples())
    order = {sample_id: index for index, sample_id in enumerate(samples)}
    output.mkdir(parents=True, exist_ok=False)
    family_manifests: list[DatasetManifest] = []
    seen: dict[str, set[str]] = {}
    part_manifests: dict[int, list[DatasetManifest]] = {}
    for family in FAMILIES:
        pairs, manifests, directory, files = merge_family(parts, family, order, output, version)
        part_manifests[len(part_manifests)] = manifests
        for case, _ in pairs:
            seen.setdefault(case.source.sample_id, set()).add(case.family)
        base = manifests[-1]
        source_parts = [
            SourcePart(
                batch=json.loads((part / "collection.json").read_text("utf-8"))["batch"],
                source_head=manifest.source_head,
                source_code_sha256=manifest.source_code_sha256,
                schema_hash=manifest.schema_hash,
                samples=sorted(
                    {
                        InputCase.model_validate_json(line).source.sample_id
                        for line in read_lines(part / family / "inputs.jsonl")
                    }
                ),
            )
            for part, manifest in zip(parts, manifests, strict=True)
        ]
        if len({manifest.schema_hash for manifest in manifests}) != 1:
            raise ValueError("parts were captured under different state schemas")
        manifest = DatasetManifest(
            version=version,
            family=family,
            cases=len(pairs),
            layers=dict(Counter(case.layer for case, _ in pairs)),
            baseline_status=dict(Counter(case.source.baseline_status for case, _ in pairs)),
            mechanical_labels=sum(ref.achieved is not None for _, ref in pairs),
            action_set_labels=sum(ref.evaluation == "action_set" for _, ref in pairs),
            rubric_cases=sum(ref.evaluation == "source_grounded_rubric" for _, ref in pairs),
            files_sha256={path.name: digest(path) for path in files},
            source_head=base.source_head,
            source_code_sha256=base.source_code_sha256,
            schema_hash=base.schema_hash,
            limitations=[
                f"{len(samples)} 个短场景的现场分布，不代表独立留出集或长程能力。",
                "采集分多段完成，各段提交见 source_parts；段间只改 trace 渲染与采集控制器。",
                "每例从空记忆起点恢复；过往 run 背景的覆盖取决于实际采集。",
                "仅机械标签进入混淆矩阵；source_grounded_rubric 需要独立评分器。",
                "旧响应仅为 baseline 审计材料，未用于构建期望答案。",
            ],
            source_parts=source_parts,
        )
        (directory / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        family_manifests.append(manifest)
    if set(seen) != set(samples):
        raise ValueError(f"merged samples differ from dataset: {sorted(set(samples) ^ set(seen))}")
    merge_sources(parts, output)
    warnings: dict[str, object] = {}
    skipped: list[str] = []
    collections = [json.loads((part / "collection.json").read_text("utf-8")) for part in parts]
    for part in parts:
        warnings.update(json.loads((part / "scope_warnings.json").read_text("utf-8")))
        skipped += (
            read_lines(part / "skipped_calls.jsonl")
            if (part / "skipped_calls.jsonl").exists()
            else []
        )
    (output / "scope_warnings.json").write_text(
        json.dumps(warnings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "skipped_calls.jsonl").write_text(
        "".join(line + "\n" for line in skipped), "utf-8", newline="\n"
    )
    (output / "skipped_calls.summary.json").write_text(
        json.dumps(
            {"count": len(skipped), "meaning": "控制账，不是缺失的模型响应"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "collection.json").write_text(
        json.dumps(
            {
                "version": version,
                "batches": [
                    {
                        "batch": item["batch"],
                        "completed": len(
                            {
                                InputCase.model_validate_json(line).source.sample_id
                                for line in read_lines(part / "plan" / "inputs.jsonl")
                            }
                        ),
                    }
                    for part, item in zip(parts, collections, strict=True)
                ],
                "builder_sha256": {
                    path.name: digest(path) for path in sorted(Path(__file__).parent.glob("*.py"))
                },
                "completed": len(samples),
                "expected": len(samples),
                "sample_ids": sorted(samples),
                "partial": False,
                "skipped_calls": len(skipped),
                "families": [item.model_dump() for item in family_manifests],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return verify(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", required=True)
    arguments = parser.parse_args()
    print(
        json.dumps(
            merge(
                [path.resolve() for path in arguments.part],
                arguments.out.resolve(),
                arguments.version,
            ),
            ensure_ascii=True,
        )
    )
