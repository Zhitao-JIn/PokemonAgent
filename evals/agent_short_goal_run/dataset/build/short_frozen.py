"""Build the deterministic frozen short-task dataset version."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

PARENT_VERSION = "v20261021_retest5"
NEW_VERSION = "v20261028_short_frozen"


def sha256_of(path: Path) -> str:
    """Return a file's SHA-256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_tasks(path: Path) -> dict[str, dict[str, Any]]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("tasks.json must contain a list")
    tasks: dict[str, dict[str, Any]] = {}
    for entry in entries:
        sample_id = entry.get("sample_id")
        if not isinstance(sample_id, str) or sample_id in tasks:
            raise ValueError(f"invalid or duplicate sample_id: {sample_id!r}")
        tasks[sample_id] = entry
    return tasks


def build_dataset(
    dataset_root: Path,
    tasks_path: Path,
    target_dir: Path | None = None,
) -> Path:
    """Create a frozen dataset from a parent version without overwriting output."""
    parent_dir = dataset_root / PARENT_VERSION
    output_dir = target_dir or dataset_root / NEW_VERSION
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing dataset: {output_dir}")

    tasks_by_sample = _read_tasks(tasks_path)
    parent_lines = (parent_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines()
    parent_samples = [json.loads(line) for line in parent_lines]
    parent_ids = [sample["sample_id"] for sample in parent_samples]
    if len(parent_ids) != len(set(parent_ids)) or set(parent_ids) != set(tasks_by_sample):
        missing = sorted(set(parent_ids) - set(tasks_by_sample))
        extra = sorted(set(tasks_by_sample) - set(parent_ids))
        raise ValueError(f"sample set mismatch: missing tasks={missing}, unknown tasks={extra}")

    output_dir.mkdir(parents=True)
    states_source = parent_dir / "states"
    states_target = output_dir / "states"
    shutil.copytree(states_source, states_target)
    state_hashes: dict[str, str] = {}
    for source in sorted(states_source.iterdir()):
        if not source.is_file():
            continue
        copied = states_target / source.name
        source_hash = sha256_of(source)
        if sha256_of(copied) != source_hash:
            raise OSError(f"state copy hash mismatch: {source.name}")
        state_hashes[f"states/{source.name}"] = source_hash

    for filename in ("rubric.json", "coverage.md"):
        shutil.copyfile(parent_dir / filename, output_dir / filename)

    updated: list[str] = []
    task_counts: dict[str, int] = {}
    for sample in parent_samples:
        task_entry = tasks_by_sample[sample["sample_id"]]
        episode, tasks = task_entry["episode"], task_entry["tasks"]
        sample["dataset_version"] = NEW_VERSION
        sample["tier"] = "short"
        sample["goals"] = [
            {
                "goal": episode["goal"],
                "success_criteria": episode["success_criteria"],
                "max_steps": episode["max_steps"],
                "tasks": tasks,
            }
        ]
        updated.append(json.dumps(sample, ensure_ascii=False, separators=(",", ":")))
        task_counts[sample["sample_id"]] = len(tasks)

    (output_dir / "samples.jsonl").write_text("\n".join(updated) + "\n", encoding="utf-8")
    source_files = {
        "tasks.json": sha256_of(tasks_path),
        "parent_samples.jsonl": sha256_of(parent_dir / "samples.jsonl"),
        "parent_rubric.json": sha256_of(parent_dir / "rubric.json"),
        "parent_coverage.md": sha256_of(parent_dir / "coverage.md"),
        **state_hashes,
    }
    revision = {
        "parent_version": PARENT_VERSION,
        "change": "冻结 plan·L1：每条样本新增 tier=short 与一张固定 task 表，其余字段与父版本一致",
        "task_counts": task_counts,
        "source_files": source_files,
    }
    (output_dir / "revision.json").write_text(
        json.dumps(revision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_dir


def main() -> None:
    dataset_root = Path(__file__).resolve().parent.parent
    tasks_path = Path(__file__).resolve().with_name("short_frozen_tasks.json")
    print(build_dataset(dataset_root, tasks_path))


if __name__ == "__main__":
    main()
