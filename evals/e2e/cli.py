"""端到端测评的命令行：`python -m evals e2e <命令>`，从仓库根运行。

dataset check [--version v1]                     核数据集冻结与引用
run [--version v1] [--split val] [--samples a,b] 批跑并出报告（真机、调模型）
    [--model M] [--vision-model M] … [--no-knowledge] [--speed N] [--timeout S]
report <报告目录>                                 按盘上产物重算报告（不调模型）
diff <报告目录 A> <报告目录 B>                    两份报告对比
run-one --report-dir D --sample S …              （批跑内部用）跑一条样本
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.e2e.checks import RULES
from evals.e2e.dataset import DatasetError, check, load_samples
from evals.e2e.report import HEADER, build_report, diff
from evals.e2e.runner import run_batch
from evals.e2e.schemas import ReportHeader

MODEL_LINKS: tuple[str, ...] = (
    "vision_model",
    "text_model",
    "judge_model",
    "verify_model",
    "plan_model",
)
"""`build_real` 的五个型号参数。"""

DEFAULT_MODEL = "deepseek-flash"
"""缺省五条链路统一的型号（与 `check_harness` 相同，intent V4 的建议口径）。"""


def main(argv: list[str] | None = None) -> int:
    """解析命令并执行，返回退出码。"""
    args = _parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except DatasetError as exc:
        print(f"数据集有问题：\n{exc}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    """命令行定义。"""
    parser = argparse.ArgumentParser(prog="python -m evals e2e")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("dataset", help="数据集操作")
    p.add_argument("action", choices=["check"])
    p.add_argument("--version", default="v1")
    p.set_defaults(func=_dataset)

    p = sub.add_parser("run", help="批跑并出报告")
    p.add_argument("--version", default="v1")
    p.add_argument("--split", default="val")
    p.add_argument("--samples", default="", help="逗号分隔的样本 id；缺省跑整个切分")
    _run_flags(p)
    p.add_argument("--timeout", type=int, default=3600, help="单条样本的超时秒数")
    p.set_defaults(func=_run)

    p = sub.add_parser("run-one", help="（内部）跑一条样本")
    p.add_argument("--report-dir", required=True)
    p.add_argument("--sample", required=True)
    _run_flags(p)
    p.set_defaults(func=_run_one)

    p = sub.add_parser("report", help="按盘上产物重算报告")
    p.add_argument("report_dir")
    p.set_defaults(func=_report)

    p = sub.add_parser("diff", help="两份报告对比")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(func=_diff)
    return parser


def _run_flags(p: argparse.ArgumentParser) -> None:
    """批跑与单跑共用的开关。"""
    p.add_argument("--model", default=DEFAULT_MODEL, help="五条链路统一的型号")
    for link in MODEL_LINKS:
        p.add_argument(f"--{link.replace('_', '-')}", default=None)
    p.add_argument("--no-knowledge", action="store_true", help="不带知识库")
    p.add_argument("--speed", type=int, default=0, help="模拟器速度（0 = 不限速）")


def _models(args: argparse.Namespace) -> dict[str, str]:
    """五个型号：单独给了用单独的，否则用 `--model`。"""
    return {link: getattr(args, link) or args.model for link in MODEL_LINKS}


def _dataset(args: argparse.Namespace) -> int:
    """`dataset check`。"""
    samples = check(args.version, set(RULES))
    judged = sum(s.check_id is not None for s in samples)
    print(f"{args.version}：{len(samples)} 条样本全部通过核对；可机械判定 {judged} 条")
    return 0


def _run(args: argparse.Namespace) -> int:
    """`run`。"""
    report_dir = run_batch(
        args.version,
        split=args.split or None,
        sample_ids=[s for s in args.samples.split(",") if s] or None,
        models=_models(args),
        knowledge=not args.no_knowledge,
        speed=args.speed,
        timeout=args.timeout,
        rule_ids=set(RULES),
    )
    print(f"报告：{report_dir / 'report.md'}")
    return 0


def _run_one(args: argparse.Namespace) -> int:
    """`run-one`（批跑子进程）。"""
    from evals.e2e.runner import run_one

    report_dir = Path(args.report_dir)
    header = ReportHeader.model_validate_json((report_dir / HEADER).read_text(encoding="utf-8"))
    [sample] = [s for s in load_samples(header.dataset_version) if s.sample_id == args.sample]
    run_one(
        sample,
        report_dir / "runs" / sample.sample_id,
        _models(args),
        knowledge=not args.no_knowledge,
        speed=args.speed,
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    """`report`。"""
    results = build_report(Path(args.report_dir))
    print(f"{len(results)} 条样本已重算：{Path(args.report_dir) / 'report.md'}")
    return 0


def _diff(args: argparse.Namespace) -> int:
    """`diff`。"""
    print(diff(Path(args.a), Path(args.b)))
    return 0


__all__ = ["main"]
