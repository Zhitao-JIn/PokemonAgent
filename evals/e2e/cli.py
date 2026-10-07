"""Inspect solver 的单样本子进程入口：python -m evals e2e run-one。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.data import DatasetError, load_samples

MODEL_LINKS = ("vision_model", "text_model", "judge_model", "verify_model", "plan_model")
DEFAULT_MODEL = "deepseek-flash"


def main(argv: list[str] | None = None) -> int:
    """解析命令并执行，返回退出码。"""
    args = _parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except DatasetError as exc:
        print(f"数据集有问题：\n{exc}", file=sys.stderr)
        return 2


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


def _run_one(args: argparse.Namespace) -> int:
    """`run-one`（solver 的子进程协议，内部）。版本号/trace 后端取自 `evals/config.json`。"""
    from evals.e2e.runner import run_one
    from evals.runconfig import load_config

    report_dir = Path(args.report_dir)
    cfg = load_config()
    version = args.version or str(cfg.get("version", "v1"))
    [sample] = [s for s in load_samples(version) if s.sample_id == args.sample]
    epoch = args.epoch
    work_name = sample.sample_id if epoch == 1 else f"{sample.sample_id}#e{epoch}"
    run_one(
        sample,
        report_dir / "runs" / work_name,
        _models(args),
        knowledge=not args.no_knowledge,
        speed=args.speed,
        epoch=epoch,
        trace_backend=args.trace_backend or str(cfg.get("trace_backend", "local")),
        watch=bool(cfg.get("watch", False)),
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    """只暴露现行 solver 使用的 run-one 子命令。"""
    parser = argparse.ArgumentParser(prog="python -m evals e2e")
    sub = parser.add_subparsers(required=True)
    command = sub.add_parser("run-one", help="跑一条样本并落盘")
    command.add_argument("--report-dir", required=True)
    command.add_argument("--sample", required=True)
    command.add_argument("--epoch", type=int, default=1)
    command.add_argument("--trace-backend", choices=["local", "langfuse"], default=None)
    command.add_argument("--version", default=None)
    _run_flags(command)
    command.set_defaults(func=_run_one)
    return parser


__all__ = ["main"]
