"""版本化 goal judge 数据包的冻结契约与读取用法。"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from evals.dataset.brain_goal_judge import JudgeCase, JudgeCaseV1, JudgeCaseV2, load, loader
from evals.dataset.brain_goal_judge.schemas import JudgeEvidence, JudgeOrigin
from evals.dataset.errors import DatasetError
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq

V1_SHA256 = "c6583cc936731270a23236bddbb76b76b16c3d4daea328399b9e5e9203e2c157"


def _write_version(root: Path, version: str, data: bytes) -> None:
    """在测试目录写入带有效清单的冻结数据文件。"""
    directory = root / version
    directory.mkdir(parents=True)
    dataset = directory / "dataset.jsonl"
    dataset.write_bytes(data)
    manifest = {
        "version": version,
        "dataset_file": dataset.name,
        "dataset_sha256": hashlib.sha256(data).hexdigest(),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_v1_load_preserves_the_frozen_bytes_and_request_type() -> None:
    cases = load()
    dataset = loader.DATASET_DIR / "v1" / "dataset.jsonl"

    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == V1_SHA256
    assert len(cases) == 4
    assert all(isinstance(case, JudgeCaseV1) for case in cases)
    assert all(isinstance(case.request, FromHarnessToBrainToolJudgeReq) for case in cases)
    assert {case.achieved for case in cases} == {True, False}


@pytest.mark.parametrize("version", ["", "../v1", "v3"])
def test_loader_rejects_invalid_or_unsupported_versions(version: str) -> None:
    with pytest.raises(DatasetError):
        load(version)


def test_loader_reads_the_frozen_v2_dataset() -> None:
    cases = load("v2")

    assert len(cases) == 257
    assert all(isinstance(case, JudgeCaseV2) for case in cases)


def test_loader_rejects_duplicate_case_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = load()[0]
    raw = case.model_dump_json().encode("utf-8")
    _write_version(tmp_path, "v1", raw + b"\n" + raw + b"\n")
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)

    with pytest.raises(DatasetError, match="重复"):
        loader.load("v1")


def test_loader_rejects_a_changed_frozen_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(loader.DATASET_DIR / "v1", tmp_path / "v1")
    dataset = tmp_path / "v1" / "dataset.jsonl"
    dataset.write_bytes(dataset.read_bytes() + b" ")
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)

    with pytest.raises(DatasetError, match="哈希"):
        loader.load("v1")


def test_v2_requires_complete_truth_metadata_and_negative_mode() -> None:
    base = load()[0]
    fields = {
        "case_id": "v2-case",
        "request": base.request,
        "achieved": False,
        "goal_family": "navigation",
        "negative_mode": "near_miss",
        "truth_method": "human",
        "check_id": None,
        "origin": JudgeOrigin(
            run_id="run",
            episode_id="episode",
            task_id="task",
            step=1,
            trace_uuid="trace-uuid",
        ),
        "request_sha256": "a" * 64,
        "evidence": [JudgeEvidence(source="trace", locator="event/1", summary="位置未到目标点")],
    }

    assert isinstance(JudgeCaseV2.model_validate(fields), JudgeCaseV2)
    assert (
        JudgeCase.model_validate({**fields, "case_id": "core-consumer"}).case_id == "core-consumer"
    )

    with pytest.raises(ValueError, match="negative_mode"):
        JudgeCaseV2.model_validate({**fields, "negative_mode": None})


def test_v2_requires_mechanical_check_id_and_concrete_evidence() -> None:
    base = load()[0]
    fields = {
        "case_id": "v2-mechanical",
        "request": base.request,
        "achieved": True,
        "goal_family": "navigation",
        "negative_mode": None,
        "truth_method": "mechanical",
        "origin": JudgeOrigin(
            run_id="run",
            episode_id="episode",
            task_id="task",
            step=1,
            trace_uuid="trace-uuid",
        ),
        "request_sha256": "b" * 64,
        "evidence": [JudgeEvidence(source="trace", locator="event/1", summary="到达目标位置")],
    }

    with pytest.raises(ValueError, match="check_id"):
        JudgeCaseV2.model_validate(fields)
    with pytest.raises(ValueError):
        JudgeCaseV2.model_validate({**fields, "check_id": "where_equals", "evidence": []})
