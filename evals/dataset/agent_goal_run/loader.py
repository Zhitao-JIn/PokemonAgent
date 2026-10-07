"""读数据集：样本（`samples.jsonl`）与 rubric（`rubric.json`），并核冻结。

数据集按版本放在本包的版本目录；冻结路径相对本版本目录。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from evals.dataset.agent_goal_run.schemas import EvalSample, Rubric
from evals.dataset.errors import DatasetError
from evals.dataset.io import contained_file, read_models, version_directory
from evals.paths import REPO_ROOT

DATASET_DIR = Path(__file__).resolve().parent


def load_samples(version: str = "v1") -> list[EvalSample]:
    """一个版本的全部样本，按文件顺序。失败：文件缺失或某行不合契约 → `DatasetError`。"""
    return read_models(version_directory(DATASET_DIR, version) / "samples.jsonl", EvalSample)


def load_rubric(version: str = "v1") -> Rubric:
    """一个版本的 rubric 与红线定义。"""
    [rubric] = read_models(
        version_directory(DATASET_DIR, version) / "rubric.json", Rubric, json_lines=False
    )
    return rubric


def sha256_of(path: Path) -> str:
    """文件内容的哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(version: str, rule_ids: set[str] | None = None) -> list[EvalSample]:
    """核一个版本：样本 id 唯一、起点文件在且哈希对得上、判据与 rubric 条目都存在。

    失败：任一条不满足 → `DatasetError`（列出全部问题，不只第一条）。
    """
    samples = load_samples(version)
    rubric = load_rubric(version)
    items = {i.item_id for i in rubric.items}
    lines = {r.line_id for r in rubric.red_lines}
    problems: list[str] = []
    seen: set[str] = set()
    for s in samples:
        if s.sample_id in seen:
            problems.append(f"{s.sample_id}：id 重复")
        seen.add(s.sample_id)
        if s.dataset_version != version:
            problems.append(f"{s.sample_id}：dataset_version={s.dataset_version}")
        _validate_start(s, DATASET_DIR / version)
        if rule_ids is not None and s.check_id is not None and s.check_id not in rule_ids:
            problems.append(f"{s.sample_id}：判据 {s.check_id} 未登记")
        problems += [f"{s.sample_id}：rubric 条目 {i} 未定义" for i in s.rubric if i not in items]
        problems += [f"{s.sample_id}：红线 {r} 未定义" for r in s.red_lines if r not in lines]
    if problems:
        raise DatasetError("\n".join(problems))
    return samples


__all__ = [
    "DATASET_DIR",
    "REPO_ROOT",
    "DatasetError",
    "check",
    "load_rubric",
    "load_samples",
    "sha256_of",
]


def load(version: str = "v1", *, rule_ids: set[str] | None = None) -> list[EvalSample]:
    """读取并核冻结，返回样本；文件、哈希与引用错误抛 DatasetError。"""
    version_directory(DATASET_DIR, version)
    return check(version, rule_ids)


class _ArchiveFiles(BaseModel):
    """冻结清单的文件引用；其余生产字段由恢复器消费。"""

    world_file: str
    memory_archive: str


def _validate_start(sample: EvalSample, directory: Path) -> None:
    """核本版本内的世界存档、记忆快照与来源哈希；失败抛 DatasetError。"""
    manifest = contained_file(directory, f"archives/{sample.start.archive}/manifest.json")
    [files] = read_models(manifest, _ArchiveFiles, json_lines=False)
    contained_file(manifest.parent, files.world_file)
    contained_file(directory, files.memory_archive)
    if sample.start.source_state:
        state = contained_file(directory, sample.start.source_state)
        if sha256_of(state) != sample.start.source_sha256:
            raise DatasetError(
                f"{sample.sample_id}：来源 .state 哈希不符 {sample.start.source_state}"
            )
