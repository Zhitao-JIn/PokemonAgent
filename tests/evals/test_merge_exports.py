"""合并多段导出：顺序、去重、请求 schema 一致与来源包并集都有显式契约。"""

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.dataset.brain_calls.dataset_contract import InputCase
from evals.dataset.brain_calls.loader import DATASET_DIR
from evals.dataset.brain_calls.merge_exports import merge_family, merge_sources
from evals.dataset.brain_calls.source_archive import SourceArchiveManifest

FAMILY = "plan"
SOURCE = DATASET_DIR / "v1" / FAMILY


def sample_order() -> dict[str, int]:
    """单批导出按报告文件名升序，合并沿用同一顺序。"""
    return {name: i for i, name in enumerate(sorted(s.sample_id for s in load_samples()))}


def split_parts(tmp_path: Path, assign: list[str]) -> list[Path]:
    """把冻结的 v1 plan 按样本分成两段导出（按 assign 给出各样本的归属 a/b）。"""
    samples = [sample.sample_id for sample in load_samples()]
    owner = dict(zip(samples, assign, strict=True))
    parts = {name: tmp_path / name for name in ("a", "b")}
    for name, root in parts.items():
        (root / FAMILY).mkdir(parents=True)
        for file in ("manifest.json", "plan.request.schema.json"):
            (root / FAMILY / file).write_bytes((SOURCE / file).read_bytes())
        for file in ("inputs.jsonl", "references.jsonl"):
            lines = (SOURCE / file).read_text("utf-8").splitlines()
            inputs = (SOURCE / "inputs.jsonl").read_text("utf-8").splitlines()
            keep = [
                line
                for line, raw in zip(lines, inputs, strict=True)
                if owner[InputCase.model_validate_json(raw).source.sample_id] == name
            ]
            (root / FAMILY / file).write_text("".join(f"{line}\n" for line in keep), "utf-8")
    return [parts["a"], parts["b"]]


@pytest.mark.skip(reason="D33: 冻结旧格式数据，待新框架重新生成后取消跳过")
def test_merge_restores_sample_order_across_parts(tmp_path: Path) -> None:
    parts = split_parts(tmp_path, ["a", "b"] * 10)

    pairs, _, _, _ = merge_family(parts, FAMILY, sample_order(), tmp_path / "out", "x")

    expected = [
        InputCase.model_validate_json(line).case_id
        for line in (SOURCE / "inputs.jsonl").read_text("utf-8").splitlines()
    ]
    assert [case.case_id for case, _ in pairs] == expected


@pytest.mark.skip(reason="D33: 冻结旧格式数据，待新框架重新生成后取消跳过")
def test_merge_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    parts = split_parts(tmp_path, ["a"] * 20)
    (parts[1] / FAMILY / "inputs.jsonl").write_bytes(
        (parts[0] / FAMILY / "inputs.jsonl").read_bytes()
    )
    (parts[1] / FAMILY / "references.jsonl").write_bytes(
        (parts[0] / FAMILY / "references.jsonl").read_bytes()
    )

    with pytest.raises(ValueError, match="duplicate case_id"):
        merge_family(
            parts,
            FAMILY,
            sample_order(),
            tmp_path / "o",
            "x",
        )


@pytest.mark.skip(reason="D33: 冻结旧格式数据，待新框架重新生成后取消跳过")
def test_merge_rejects_parts_with_different_request_schemas(tmp_path: Path) -> None:
    parts = split_parts(tmp_path, ["a", "b"] * 10)
    (parts[1] / FAMILY / "plan.request.schema.json").write_text("{}", "utf-8")

    with pytest.raises(ValueError, match="schema differs"):
        merge_family(
            parts,
            FAMILY,
            sample_order(),
            tmp_path / "o",
            "x",
        )


def write_sources(root: Path, entries: dict[str, bytes]) -> None:
    """写一个最小来源包及其清单。"""
    import hashlib

    root.mkdir(parents=True)
    with ZipFile(root / "sources.zip", "w") as stream:
        for name, data in entries.items():
            stream.writestr(name, data)
    manifest = SourceArchiveManifest(
        archive="sources.zip",
        archive_sha256=hashlib.sha256((root / "sources.zip").read_bytes()).hexdigest(),
        entries={name: hashlib.sha256(data).hexdigest() for name, data in entries.items()},
    )
    (root / "sources.manifest.json").write_text(manifest.model_dump_json(), "utf-8")


def test_sources_are_united_when_entries_do_not_conflict(tmp_path: Path) -> None:
    write_sources(tmp_path / "a", {"x/1.json": b"1", "shared.json": b"s"})
    write_sources(tmp_path / "b", {"y/2.json": b"2", "shared.json": b"s"})
    (tmp_path / "out").mkdir()

    manifest = merge_sources([tmp_path / "a", tmp_path / "b"], tmp_path / "out")

    assert set(manifest.entries) == {"x/1.json", "y/2.json", "shared.json"}
    with ZipFile(tmp_path / "out" / "sources.zip") as stream:
        assert json.loads(json.dumps(sorted(stream.namelist()))) == sorted(manifest.entries)


def test_sources_with_conflicting_bytes_are_rejected(tmp_path: Path) -> None:
    write_sources(tmp_path / "a", {"shared.json": b"one"})
    write_sources(tmp_path / "b", {"shared.json": b"two"})
    (tmp_path / "out").mkdir()

    with pytest.raises(ValueError, match="conflicts between parts"):
        merge_sources([tmp_path / "a", tmp_path / "b"], tmp_path / "out")
