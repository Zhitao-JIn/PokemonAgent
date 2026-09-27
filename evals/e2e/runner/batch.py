"""批跑：写口径头 → 每条样本一个子进程跑 `run-one` → 出报告。

每条样本独立子进程：模拟器与模型客户端不跨样本残留，一条样本卡死或崩溃不连累别的（超时即杀，
该条记"没有批跑记录"，报表里列为无效）。产物落在仓库根的 `eval_results/<report_id>/`（不进 git）。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

import pokemon_agent.config as config
from evals.e2e.dataset import REPO_ROOT, check, load_rubric, samples_digest
from evals.e2e.report import HEADER, build_report
from evals.e2e.schemas import EvalSample, ReportHeader

RESULTS_ROOT = REPO_ROOT / "eval_results" / "e2e"


def run_batch(
    version: str,
    *,
    split: str | None,
    sample_ids: list[str] | None,
    models: dict[str, str],
    knowledge: bool,
    speed: int,
    timeout: int,
    rule_ids: set[str],
) -> Path:
    """跑一批并出报告，返回报告目录。失败：数据集核不过 → `DatasetError`（一条都不跑）。"""
    samples = _select(check(version, rule_ids), split, sample_ids)
    report_id = time.strftime("%Y%m%d-%H%M%S")
    report_dir = RESULTS_ROOT / report_id
    (report_dir / "runs").mkdir(parents=True)

    # 步骤 1：口径头。
    header = _header(report_id, version, samples, models, knowledge)
    (report_dir / HEADER).write_text(header.model_dump_json(indent=2), encoding="utf-8")

    # 步骤 2：逐条子进程跑，只落盘。
    for n, sample in enumerate(samples, start=1):
        print(f"[{n}/{len(samples)}] {sample.sample_id}", flush=True)
        cmd = [
            sys.executable, "-m", "evals", "e2e", "run-one",
            "--report-dir", str(report_dir), "--sample", sample.sample_id,
            "--speed", str(speed), *(["--no-knowledge"] if not knowledge else []),
            *[a for k, v in models.items() for a in (f"--{k.replace('_', '-')}", v)],
        ]  # fmt: skip
        try:
            subprocess.run(cmd, cwd=REPO_ROOT, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            print(f"    超时 {timeout}s，已杀", flush=True)

    # 步骤 3：判定与报表（纯函数，可用 `python -m evals report` 重算）。
    build_report(report_dir)
    return report_dir


def _select(
    samples: list[EvalSample], split: str | None, ids: list[str] | None
) -> list[EvalSample]:
    """按切分与 id 过滤；给了 id 就只跑这些（顺序照数据集）。"""
    chosen = [s for s in samples if split is None or s.split == split]
    if ids:
        missing = set(ids) - {s.sample_id for s in chosen}
        assert not missing, f"数据集里没有这些样本：{sorted(missing)}"
        chosen = [s for s in chosen if s.sample_id in ids]
    return chosen


def _header(
    report_id: str, version: str, samples: list[EvalSample], models: dict[str, str], knowledge: bool
) -> ReportHeader:
    """口径头：代码版本、模型、全部旋钮、数据集与 rubric 版本、知识库。"""
    knobs = {k: repr(getattr(config, k)) for k in dir(config) if k.isupper()}
    return ReportHeader(
        report_id=report_id,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        git_commit=_git("rev-parse", "HEAD"),
        git_dirty=bool(_git("status", "--porcelain")),
        models=models,
        config=knobs,
        dataset_version=version,
        samples_sha256=samples_digest(samples),
        rubric_version=load_rubric(version).version,
        knowledge=_knowledge_digest() if knowledge else "off",
        sample_ids=[s.sample_id for s in samples],
    )


def _git(*args: str) -> str:
    """跑一条 git 命令取输出；没有 git 时给空串。"""
    try:
        out = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return out.stdout.strip()


def _knowledge_digest() -> str:
    """知识库源文件（`*.md`）的整体哈希。"""
    digest = hashlib.sha256()
    for path in sorted((REPO_ROOT / "memory" / "knowledge_memory").glob("*.md")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


__all__ = ["RESULTS_ROOT", "run_batch"]
