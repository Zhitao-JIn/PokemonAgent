"""分别发布四个可运行版本；每种能力保留完整审阅覆盖和排除清单。"""

import hashlib
import json
from pathlib import Path

from evals.dataset.brain_calls import load_inputs, load_references
from evals.dataset.brain_calls.native_versions import choose_case, judge_case
from evals.paths import REPO_ROOT

from .contract import Annotation
from .loader import ROOT, load
from .references import combine

VERSIONS: dict[str, str] = {"choose": "v3", "judge": "v4", "plan": "v2", "decompose": "v2"}


def write_json(path: Path, value: object) -> None:
    """新发布文件由调用方保证不存在。"""
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n")


def native(family: str, rows: list[Annotation], output: Path, version: str) -> None:
    """生成 choose/judge 的原生记录；旧版本标签与文件保持原字节。"""
    cases, references = load_inputs(family), load_references(family)
    records = []
    for case, reference, annotation in zip(cases, references, rows, strict=True):
        if annotation.status != "labelled":
            continue
        ref = combine(reference, annotation)
        truth = (
            "mechanical" if annotation.method == "mechanical_preexisting" else "history_adjudicated"
        )
        record = (
            judge_case(case, ref, truth_method=truth)
            if family == "judge"
            else choose_case(case, ref)
        )
        if annotation.method != "mechanical_preexisting":
            record = record.model_copy(
                update={
                    "truth_method" if family == "judge" else "label_source": "history_adjudicated"
                }
            )
        records.append(record)
    name = "dataset.jsonl" if family == "judge" else "cases.jsonl"
    path = output / name
    path.write_text(
        "".join(record.model_dump_json() + "\n" for record in records), "utf-8", newline="\n"
    )
    write_json(
        output / "manifest.json",
        {
            "version": version,
            "dataset_file": name,
            "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    )


def publish() -> None:
    """使用通过哈希/证据核验的审阅数据，新目录已存在则显式失败。"""
    for family, version in VERSIONS.items():
        rows = load(family)
        output = REPO_ROOT / "evals/dataset" / f"brain_{family}" / version
        output.mkdir(exist_ok=False)
        if family in {"choose", "judge"}:
            native(family, rows, output, version)
        else:
            previous = output.parent / "v1/manifest.json"
            manifest = json.loads(previous.read_text("utf-8"))
            manifest.update(
                {
                    "version": version,
                    "annotation_version": "v1",
                    "annotation_sha256": hashlib.sha256(
                        (ROOT / "v1" / f"{family}.jsonl").read_bytes()
                    ).hexdigest(),
                }
            )
            write_json(output / "manifest.json", manifest)
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
                "annotation_version": "v1",
                "baseline_answers_used_as_gold": False,
            },
        )


if __name__ == "__main__":
    publish()
