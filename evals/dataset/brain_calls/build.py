"""二十例录制转为五类数据、可评分子集与可移植审计包；不调用模型。"""

import argparse
import json
from pathlib import Path

from .baseline_score import evaluate_baseline
from .build_report import write_report
from .native_versions import publish
from .source_archive import archive_sources
from .verify_dataset import verify


def build(batch: Path, output: Path, judge_output: Path, choose_output: Path) -> dict[str, int]:
    """目录必须不存在；失败保留已写数据供排查，不覆盖任何冻结版本。"""
    archive_sources(batch, output)
    counts = verify(output)
    counts["judge_labelled"] = publish(output, "judge", judge_output, judge_output.name)
    counts["choose_labelled"] = publish(output, "choose", choose_output, choose_output.name)
    baseline = evaluate_baseline(output, batch)
    (output / "baseline_scores.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    write_report(batch, output)
    return counts


def main() -> None:
    """显式路径控制版本发布；源批次须完成全部二十例与审计门。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--judge-out", type=Path, required=True)
    parser.add_argument("--choose-out", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.batch.resolve(),
                args.out.resolve(),
                args.judge_out.resolve(),
                args.choose_out.resolve(),
            ),
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
