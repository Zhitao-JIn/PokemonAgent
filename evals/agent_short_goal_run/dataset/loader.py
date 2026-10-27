"""读数据集：样本（`samples.jsonl`）与 rubric（`rubric.json`），并核冻结。

数据集按版本放在本包的版本目录；冻结路径相对本版本目录。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from evals.agent_short_goal_run.dataset.schemas import EvalSample, Rubric
from evals.dataset.errors import DatasetError
from evals.dataset.io import contained_file, read_models, version_directory
from evals.paths import REPO_ROOT

DATASET_DIR = Path(__file__).resolve().parent


def load_samples(version: str = "v1") -> list[EvalSample]:
    """一个版本的全部样本，按文件顺序。失败：文件缺失或某行不合契约 → `DatasetError`。"""
    return read_models(version_directory(DATASET_DIR, version) / "samples.jsonl", EvalSample)


def validate_tiers(samples: Sequence[EvalSample]) -> None:
    """档位与冻结内容的一致性（D8）：三档各自的必需项，违反即 `DatasetError`。

    - `long`：`goals` 为空（目标表由 planner 建，与现状一致）；
    - `mid`：`goals` 非空、各条 `tasks` 全空（只冻结 episode 目标表）；
    - `short`：`goals` 恰一条、它的 `tasks` 非空（连这一局的 task 表一起冻结）。

    失败：任一档位不合规 → `DatasetError`（列出全部问题，不只第一条）。
    """
    problems: list[str] = []
    for sample in samples:
        goals = sample.goals
        if sample.tier == "long":
            if goals:
                problems.append(f"{sample.sample_id}：long 档不该带 goals（{len(goals)} 条）")
        elif sample.tier == "mid":
            if not goals:
                problems.append(f"{sample.sample_id}：mid 档需要非空 goals")
            problems += [
                f"{sample.sample_id}：mid 档第 {i} 条目标不该带 tasks"
                for i, goal in enumerate(goals, start=1)
                if goal.tasks
            ]
        else:
            if len(goals) != 1:
                problems.append(
                    f"{sample.sample_id}：short 档需要恰一条 goals（实际 {len(goals)}）"
                )
            problems += [
                f"{sample.sample_id}：short 档第 {i} 条目标需要非空 tasks"
                for i, goal in enumerate(goals, start=1)
                if not goal.tasks
            ]
    if problems:
        raise DatasetError("\n".join(problems))


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
    validate_tiers(samples)
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
    "validate_tiers",
]


def load(version: str = "v1", *, rule_ids: set[str] | None = None) -> list[EvalSample]:
    """读取并核冻结，返回样本；文件、哈希与引用错误抛 DatasetError。"""
    version_directory(DATASET_DIR, version)
    return check(version, rule_ids)


def _validate_start(sample: EvalSample, directory: Path) -> None:
    """核本版本内的原始世界状态及其哈希；失败抛 DatasetError。"""
    state = contained_file(directory, sample.start.source_state)
    if sha256_of(state) != sample.start.source_sha256:
        raise DatasetError(f"{sample.sample_id}：来源 .state 哈希不符 {sample.start.source_state}")
