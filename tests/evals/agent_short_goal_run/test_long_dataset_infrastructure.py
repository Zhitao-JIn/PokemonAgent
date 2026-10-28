"""长期样本记忆种子的公开加载契约示例。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.agent_short_goal_run.dataset import loader
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.common.eval_services import _knowledge_topic
from evals.dataset.errors import DatasetError


def _sample(seed_path: str | None = None, manifest_sha256: str = "") -> dict:
    value = {
        "sample_id": "synthetic_long",
        "dataset_version": "synthetic",
        "granularity": "run",
        "tier": "long",
        "category": "test",
        "start": {"kind": "state", "source_state": "start.state", "source_sha256": ""},
        "goal": "goal",
        "success_criteria": "criteria",
        "max_steps": 1,
        "behavior": "behavior",
        "check_id": None,
        "rubric": [],
        "red_lines": [],
        "k_metric": "pass_at_k",
        "split": "test",
    }
    if seed_path is not None:
        value["initial_memory"] = {"path": seed_path, "manifest_sha256": manifest_sha256}
    return value


def _write_dataset(tmp_path: Path, sample: dict) -> None:
    version = tmp_path / "synthetic"
    version.mkdir(exist_ok=True)
    (version / "start.state").write_bytes(b"state")
    sample["start"]["source_sha256"] = hashlib.sha256(b"state").hexdigest()
    (version / "samples.jsonl").write_text(json.dumps(sample) + "\n", encoding="utf-8")
    (version / "rubric.json").write_text(
        json.dumps({"version": "synthetic", "items": [], "red_lines": []}), encoding="utf-8"
    )


def test_eval_sample_defaults_keep_optional_memory_fields_empty() -> None:
    sample = EvalSample.model_validate(_sample())

    assert sample.initial_memory is None
    assert sample.knowledge_exclude_topics == []


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        ('---\n{"metadata":{"topic":"method"}}\n---\nbody', "method"),
        ("---\nnot-json\n---\nbody", None),
        ("body without frontmatter", None),
    ],
)
def test_knowledge_topic_reads_only_valid_json_frontmatter(
    tmp_path: Path, contents: str, expected: str | None
) -> None:
    path = tmp_path / "topic.md"
    path.write_text(contents, encoding="utf-8")

    assert _knowledge_topic(path) == expected


def test_initial_memory_is_restricted_to_long_tier() -> None:
    sample = _sample()
    sample["tier"] = "mid"
    sample["initial_memory"] = {"path": "seed", "manifest_sha256": "abc"}
    parsed = EvalSample.model_validate(sample)

    with pytest.raises(DatasetError, match="只允许 long"):
        loader.validate_tiers([parsed])


def test_loader_checks_manifest_hashes_and_rejects_extra_files(monkeypatch, tmp_path) -> None:
    seed = tmp_path / "synthetic" / "seed"
    seed.mkdir(parents=True)
    data = seed / "run_memory" / "run.json"
    data.parent.mkdir()
    data.write_text("record", encoding="utf-8")
    manifest = {
        "files": [{"path": "run_memory/run.json", "sha256": hashlib.sha256(b"record").hexdigest()}]
    }
    (seed / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = hashlib.sha256((seed / "MANIFEST.json").read_bytes()).hexdigest()
    sample = _sample("seed", manifest_hash)
    _write_dataset(tmp_path, sample)
    fake_knowledge = tmp_path / "knowledge_memory"
    fake_knowledge.mkdir()
    (fake_knowledge / "topic.md").write_text(
        '---\n{ "metadata": {"topic": "known"} }\n---\nbody', encoding="utf-8"
    )
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)
    monkeypatch.setattr(loader, "REPO_ROOT", tmp_path)

    assert len(loader.check("synthetic")) == 1
    (seed / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(DatasetError, match="清单不一致"):
        loader.check("synthetic")


@pytest.mark.parametrize("bad_hash", ["manifest", "record"])
def test_loader_rejects_manifest_or_record_hash_mismatch(monkeypatch, tmp_path, bad_hash) -> None:
    seed = tmp_path / "synthetic" / "seed"
    record = seed / "run_memory" / "run.json"
    record.parent.mkdir(parents=True)
    record.write_text("record", encoding="utf-8")
    digest = "0" * 64 if bad_hash == "record" else hashlib.sha256(b"record").hexdigest()
    manifest = {"files": [{"path": "run_memory/run.json", "sha256": digest}]}
    (seed / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    actual_manifest_hash = hashlib.sha256((seed / "MANIFEST.json").read_bytes()).hexdigest()
    _write_dataset(
        tmp_path,
        _sample("seed", "0" * 64 if bad_hash == "manifest" else actual_manifest_hash),
    )
    fake_knowledge = tmp_path / "knowledge_memory"
    fake_knowledge.mkdir()
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)
    monkeypatch.setattr(loader, "REPO_ROOT", tmp_path)

    with pytest.raises(DatasetError, match="哈希不符"):
        loader.check("synthetic")


def test_loader_rejects_unknown_topic_and_seed_knowledge_collection(monkeypatch, tmp_path) -> None:
    seed = tmp_path / "synthetic" / "seed"
    (seed / "knowledge_memory").mkdir(parents=True)
    (seed / "MANIFEST.json").write_text('{"files": []}', encoding="utf-8")
    manifest_hash = hashlib.sha256((seed / "MANIFEST.json").read_bytes()).hexdigest()
    sample = _sample("seed", manifest_hash)
    sample["knowledge_exclude_topics"] = ["missing"]
    _write_dataset(tmp_path, sample)
    fake_knowledge = tmp_path / "knowledge_memory"
    fake_knowledge.mkdir()
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)
    monkeypatch.setattr(loader, "REPO_ROOT", tmp_path)

    with pytest.raises(DatasetError, match="不存在|knowledge_memory"):
        loader.check("synthetic")
