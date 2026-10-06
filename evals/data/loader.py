"""读数据集：样本（`samples.jsonl`）与 rubric（`rubric.json`），并核冻结。

数据集按版本放在 `evals/dataset/<版本>/`；样本里的路径一律相对仓库根。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from evals.schema import EvalSample, Rubric

DATASET_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATASET_DIR.parents[1]


class DatasetError(Exception):
    """数据集本身有问题：文件缺、哈希对不上、引用了不存在的判据或 rubric 条目。"""


def load_samples(version: str) -> list[EvalSample]:
    """一个版本的全部样本，按文件顺序。失败：文件缺失或某行不合契约 → `DatasetError`。"""
    path = DATASET_DIR / version / "samples.jsonl"
    if not path.is_file():
        raise DatasetError(f"没有数据集 {version}（{path}）")
    samples = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            samples.append(EvalSample.model_validate_json(line))
        except ValueError as exc:
            raise DatasetError(f"{path.name} 第 {n} 行不合契约：{exc}") from exc
    return samples


def load_rubric(version: str) -> Rubric:
    """一个版本的 rubric 与红线定义。"""
    path = DATASET_DIR / version / "rubric.json"
    if not path.is_file():
        raise DatasetError(f"数据集 {version} 没有 rubric.json")
    return Rubric.model_validate_json(path.read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    """文件内容的哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(version: str, rule_ids: set[str]) -> list[EvalSample]:
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
        if s.start.kind == "archive":
            archive = DATASET_DIR / version / "archives" / s.start.archive
            if not (archive / "manifest.json").is_file():
                problems.append(
                    f"{s.sample_id}：起点存档缺失 {s.start.archive}"
                    "（python -m evals.data.pack 重打）"
                )
            if s.start.source_state:
                state = REPO_ROOT / s.start.source_state
                digest_ok = state.is_file() and sha256_of(state) == s.start.source_sha256
                problems += (
                    []
                    if digest_ok
                    else [f"{s.sample_id}：打包来源 .state 缺失或哈希对不上 {s.start.source_state}"]
                )
        if s.check_id is not None and s.check_id not in rule_ids:
            problems.append(f"{s.sample_id}：判据 {s.check_id} 未登记")
        problems += [f"{s.sample_id}：rubric 条目 {i} 未定义" for i in s.rubric if i not in items]
        problems += [f"{s.sample_id}：红线 {r} 未定义" for r in s.red_lines if r not in lines]
    if problems:
        raise DatasetError("\n".join(problems))
    return samples


def samples_digest(samples: list[EvalSample]) -> str:
    """一组样本定义的整体哈希（进口径头）。"""
    blob = "\n".join(s.model_dump_json() for s in samples)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


__all__ = [
    "DATASET_DIR",
    "REPO_ROOT",
    "DatasetError",
    "check",
    "load_rubric",
    "load_samples",
    "samples_digest",
    "sha256_of",
]
