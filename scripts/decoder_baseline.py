"""冻结帧通用decoder基线：逐字段精确比较，保留失败ID、场景分布和前后回退。"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from evals.data.frames.schemas import ScreenSample
from evals.solvers.decode import decode_frame

FIELDS = (
    "scene",
    "overlay",
    "dialog_text",
    "options",
    "option_grid",
    "option_details",
    "cursor",
    "cursor_cell",
    "has_cursor",
    "quantity_box",
    "in_battle",
    "strict_dialog",
    "screen",
)


def has_content(field: str, value: object) -> bool:
    """空白也参与总体统计；内容子集以期望值定义，不由decoder预测决定。"""
    if field == "option_details":
        return isinstance(value, list) and any(value)
    if field == "cursor_cell":
        return value is not None
    return bool(value)


def evaluate(samples: Path, truth: Path) -> dict[str, Any]:
    """读取全部独立真值；不修改真值、不调用模型、不推进模拟器。"""
    labels = {
        row["sample_id"]: row
        for row in map(json.loads, truth.read_text(encoding="utf-8").splitlines())
    }
    statistics: dict[str, Any] = {
        field: {
            "correct": 0,
            "total": 0,
            "content_correct": 0,
            "content_total": 0,
            "wrong_ids": [],
            "by_scene": {},
        }
        for field in FIELDS
    }
    records = []
    seen: set[str] = set()
    for line in samples.read_text(encoding="utf-8").splitlines():
        frame = ScreenSample.model_validate_json(line)
        if frame.sample_id in seen:
            raise ValueError(f"duplicate sample {frame.sample_id}")
        seen.add(frame.sample_id)
        expected = labels[frame.sample_id]
        actual = decode_frame(frame).model_dump(mode="json")
        differences = compare(frame.sample_id, expected, actual, statistics)
        if differences:
            records.append({"sample_id": frame.sample_id, "wrong": differences})
    if seen != set(labels):
        raise ValueError("sample IDs and reference truth IDs must match")
    return finish(statistics, records, samples, truth, len(labels))


def finish(
    statistics: dict[str, Any],
    records: list[dict[str, Any]],
    samples: Path,
    truth: Path,
    count: int,
) -> dict[str, Any]:
    """汇总字段准确率及输入指纹，保留所有失败值供逐帧检查。"""
    for item in statistics.values():
        item["accuracy"] = item["correct"] / item["total"]
        item["content_accuracy"] = (
            item["content_correct"] / item["content_total"] if item["content_total"] else None
        )
    return {
        "status": "labelled_truth",
        "fields": statistics,
        "truth_sha256": hashlib.sha256(truth.read_bytes()).hexdigest(),
        "samples_sha256": hashlib.sha256(samples.read_bytes()).hexdigest(),
        "comparison": "exact field equality, ordered lists and grid, no normalization",
        "excluded": ["at_start", "covered_by_script", "covered", "takeover.*", "terrain.*"],
        "frames": count,
        "all_fields_correct_frames": count - len(records),
        "differences": records,
    }


def compare(
    sample_id: str, expected: dict[str, Any], actual: dict[str, Any], statistics: dict[str, Any]
) -> dict[str, Any]:
    """累加每个字段与场景的分母；输出缺键按错误处理。"""
    differences = {}
    scene = expected["scene_truth"]["scene"]
    for field in FIELDS:
        group = "scene" if field == "scene" else "screen"
        want = expected[f"{group}_truth"][field]
        correct = field in actual[group] and actual[group][field] == want
        stat = statistics[field]
        buckets = [
            stat,
            stat["by_scene"].setdefault(
                scene, {"correct": 0, "total": 0, "content_correct": 0, "content_total": 0}
            ),
        ]
        for bucket in buckets:
            bucket["total"] += 1
            bucket["correct"] += int(correct)
            if has_content(field, want):
                bucket["content_total"] += 1
                bucket["content_correct"] += int(correct)
        if not correct:
            stat["wrong_ids"].append(sample_id)
            differences[f"{group}.{field}"] = {"expected": want, "actual": actual[group].get(field)}
    return differences


def changes(report: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """同一真值与样本哈希才允许比较；逐字段报告修复和回退的帧ID。"""
    for name in ("truth_sha256", "samples_sha256"):
        if report[name] != previous[name]:
            raise ValueError(f"baseline comparison requires matching {name}")
    result = {}
    for field in FIELDS:
        old = set(previous["fields"][field]["wrong_ids"])
        new = set(report["fields"][field]["wrong_ids"])
        result[field] = {"fixed": sorted(old - new), "regressed": sorted(new - old)}
    return result


def main() -> None:
    """调用方提供阶段名称及输出路径；保留原始基线文件，拒绝覆盖前序报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.previous.resolve() or args.output.exists():
        raise ValueError("output must be a new report path")
    report = evaluate(
        Path("evals/data/frames/dataset/v2/samples.jsonl"), Path("evals/data/frames/truth.jsonl")
    )
    report["changes"] = changes(report, json.loads(args.previous.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "correct_frames": report["all_fields_correct_frames"],
                "errors": {k: len(v["wrong_ids"]) for k, v in report["fields"].items()},
                "regressions": {
                    k: v["regressed"] for k, v in report["changes"].items() if v["regressed"]
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
