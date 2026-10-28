"""读数据集：样本（`samples.jsonl`）与 rubric（`rubric.json`），并核冻结。

数据集按版本放在本包的版本目录；冻结路径相对本版本目录。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath

from evals.agent_short_goal_run.dataset.schemas import EvalSample, Rubric
from evals.dataset.errors import DatasetError
from evals.dataset.io import contained_file, read_models, version_directory
from evals.paths import REPO_ROOT

DATASET_DIR = Path(__file__).resolve().parent


def load_samples(version: str) -> list[EvalSample]:
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
        if sample.initial_memory is not None and sample.tier != "long":
            problems.append(f"{sample.sample_id}：initial_memory 只允许 long 档")
    if problems:
        raise DatasetError("\n".join(problems))


def load_rubric(version: str) -> Rubric:
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
        problems += _validate_initial_memory(s, DATASET_DIR / version)
        problems += _validate_knowledge_topics(s.knowledge_exclude_topics)
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


def load(version: str, *, rule_ids: set[str] | None = None) -> list[EvalSample]:
    """读取并核冻结，返回样本；文件、哈希与引用错误抛 DatasetError。"""
    version_directory(DATASET_DIR, version)
    return check(version, rule_ids)


def _validate_start(sample: EvalSample, directory: Path) -> None:
    """核本版本内的原始世界状态及其哈希；失败抛 DatasetError。"""
    state = contained_file(directory, sample.start.source_state)
    if sha256_of(state) != sample.start.source_sha256:
        raise DatasetError(f"{sample.sample_id}：来源 .state 哈希不符 {sample.start.source_state}")


def _validate_initial_memory(sample: EvalSample, directory: Path) -> list[str]:
    """校验种子路径、manifest 哈希、文件清单和文件内容哈希。"""
    seed = sample.initial_memory
    if seed is None:
        return []
    relative = PurePosixPath(seed.path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in seed.path
        or PureWindowsPath(seed.path).drive
    ):
        return [f"{sample.sample_id}：initial_memory.path 必须是版本目录内相对路径"]
    root = (directory / Path(*relative.parts)).resolve()
    if not root.is_relative_to(directory.resolve()) or not root.is_dir():
        return [f"{sample.sample_id}：initial_memory 目录不存在或越界：{seed.path}"]
    manifest = root / "MANIFEST.json"
    if not manifest.is_file():
        return [f"{sample.sample_id}：缺少 MANIFEST.json"]
    if sha256_of(manifest) != seed.manifest_sha256:
        return [f"{sample.sample_id}：MANIFEST.json 哈希不符"]
    problems: list[str] = []
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        listed = {entry["path"]: entry["sha256"] for entry in entries}
    except (ValueError, KeyError, TypeError) as error:
        return [f"{sample.sample_id}：MANIFEST.json 格式错误：{error}"]
    all_paths = {path.relative_to(root).as_posix() for path in root.rglob("*")}
    actual = {name for name in all_paths if (root / name).is_file()}
    if "knowledge_memory" in {part for item in all_paths for part in PurePosixPath(item).parts}:
        problems.append(f"{sample.sample_id}：种子不允许包含 knowledge_memory")
    expected = set(listed) | {"MANIFEST.json"}
    if actual != expected:
        problems.append(f"{sample.sample_id}：种子文件与 manifest 清单不一致")
    for name, digest in listed.items():
        item = PurePosixPath(name)
        if item.is_absolute() or ".." in item.parts or "\\" in name:
            problems.append(f"{sample.sample_id}：manifest 路径不安全：{name}")
            continue
        path = (root / Path(*item.parts)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            problems.append(f"{sample.sample_id}：manifest 文件缺失或越界：{name}")
        elif sha256_of(path) != digest:
            problems.append(f"{sample.sample_id}：种子文件哈希不符：{name}")
    return problems


def _validate_knowledge_topics(topics: list[str]) -> list[str]:
    """仅允许引用仓库知识库 frontmatter metadata.topic 中真实存在的主题。"""
    known: set[str] = set()
    for path in (REPO_ROOT / "memory" / "knowledge_memory").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end < 0:
            continue
        try:
            metadata = json.loads(text[4:end])
        except json.JSONDecodeError:
            continue
        topic = metadata.get("metadata", {}).get("topic") if isinstance(metadata, dict) else None
        if isinstance(topic, str):
            known.add(topic)
    return [
        f"knowledge_exclude_topics 中主题不存在：{topic}" for topic in topics if topic not in known
    ]
