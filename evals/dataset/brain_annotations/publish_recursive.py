"""把递归规划批次的旁账发布成四个能力版本；每个版本固定输入、参考与旁账字节指纹。"""

import hashlib
import json
import sys
from pathlib import Path

from evals.dataset.brain_calls import load_inputs, load_references
from evals.dataset.brain_calls.loader import directory_for
from evals.dataset.brain_calls.native_versions import judge_case
from evals.paths import REPO_ROOT

from .contract import Annotation
from .loader import ROOT, load
from .references import combine

FAMILIES = ("choose", "judge", "plan", "decompose")


def write_json(path: Path, value: object) -> None:
    """新发布文件由调用方保证不存在。"""
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n")


def judge_records(version: str, rows: list[Annotation], output: Path) -> None:
    """judge 原生记录：二元真值、决策标签与真值方式如实标注；排除项不进入。"""
    cases, references = load_inputs("judge", version), load_references("judge", version)
    records = []
    for case, reference, row in zip(cases, references, rows, strict=True):
        if row.status != "labelled":
            continue
        truth = "mechanical" if row.method == "mechanical_preexisting" else "history_adjudicated"
        record = judge_case(case, combine(reference, row), truth_method=truth)
        records.append(record.model_copy(update={"expected_decision": row.expected_decision}))
    path = output / "dataset.jsonl"
    path.write_text(
        "".join(record.model_dump_json() + "\n" for record in records), "utf-8", newline="\n"
    )
    write_json(
        output / "manifest.json",
        {
            "version": version,
            "dataset_file": path.name,
            "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    )


def capability_manifest(family: str, version: str, output: Path, count: int) -> None:
    """choose/plan/decompose 只固定指纹，运行时由旁账合成建议式参考。"""
    _, source = directory_for(family, version)
    write_json(
        output / "manifest.json",
        {
            "version": version,
            "family": family,
            "collection_version": version,
            "cases": count,
            "inputs_sha256": source.files_sha256["inputs.jsonl"],
            "references_sha256": source.files_sha256["references.jsonl"],
            "annotation_version": version,
            "annotation_sha256": hashlib.sha256(
                (ROOT / version / f"{family}.jsonl").read_bytes()
            ).hexdigest(),
        },
    )


def publish(version: str) -> None:
    """四个能力版本同名；已存在则显式失败，旧版本不被覆盖。"""
    for family in FAMILIES:
        rows = load(family, version)
        output = REPO_ROOT / "evals/dataset" / f"brain_{family}" / version
        output.mkdir(exist_ok=False)
        if family == "judge":
            judge_records(version, rows, output)
        else:
            capability_manifest(family, version, output, len(rows))
        write_json(
            output / "coverage.json",
            {
                "source_cases": len(rows),
                "labelled": sum(row.status == "labelled" for row in rows),
                "excluded": [
                    {"case_id": row.case_id, "status": row.status, "reason": row.rationale}
                    for row in rows
                    if row.status != "labelled"
                ],
                "annotation_version": version,
                "reference_role": "decision_labels"
                if family == "judge"
                else "non_exhaustive_suggestions",
                "baseline_answers_used_as_gold": False,
            },
        )


if __name__ == "__main__":
    publish(sys.argv[1])
