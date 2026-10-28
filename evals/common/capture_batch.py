"""重打二十起点并串行采集全脑；保持源存档、配置和代码指纹。"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from evals.agent_short_goal_run.dataset.loader import DATASET_DIR, load_samples
from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.common.capture_audit import CaptureAudit, audit_capture
from evals.common.capture_selection import CAPTURE_DATASET_VERSION
from evals.common.capture_services import capture_services, start_process, stop_process
from evals.common.invocation import write_record
from evals.paths import REPO_ROOT
from evals.runconfig import load_config
from pokemon_agent.env import load_env_file
from pokemon_agent.harness.checkpoint.manifest import state_schema_hash
from pokemon_agent.schemas.harness.domain import RunResult
from pokemon_agent.settings import BudgetConfig


class PackReport(BaseModel):
    """新起点与本次执行版本，原始 state 哈希单独记录。"""

    archive_root: str | None = None
    effective_budget: BudgetConfig | None = None
    sample_sha256: str | None = None
    archive_payload_hashes: dict[str, str] = Field(default_factory=dict)
    git_head: str
    schema_hash: str
    source_hashes: dict[str, str]
    archive_hashes: dict[str, str]
    configuration_sha256: str
    code_sha256: str


class CaseReport(BaseModel):
    """业务失败仍保留样本；录制遗漏或进程异常须明确报告。"""

    work_directory: str | None = None
    interrupted: bool = False
    sample_id: str
    git_head: str
    exit_code: int
    error: str = ""
    audit: CaptureAudit
    run_result: RunResult | None = None


class BatchReport(BaseModel):
    """当前已完成样本；中断时也保存已有证据，不伪报二十例完成。"""

    expected: int = 20
    completed: list[CaseReport] = Field(default_factory=list)
    error: str = ""


def git_head() -> str:
    """读取调用时的实际提交；Git 失败中止，不填 unknown。"""
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def sha256(path: Path) -> str:
    """按字节校验来源与配置，不受文本行尾渲染影响。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_sha256() -> str:
    """固定运行代码与 prompt；不把采集输出或 archive 变动误记为改代码。"""
    digest = hashlib.sha256()
    paths = [
        path
        for root in ("pokemon_agent", "evals")
        for path in (REPO_ROOT / root).rglob("*")
        if path.is_file() and path.suffix in (".py", ".md")
    ]
    for path in sorted(paths):
        digest.update(path.relative_to(REPO_ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def source_states(samples: list[EvalSample]) -> dict[str, str]:
    """核全部原始状态；先核完二十例再执行任何重打。"""
    result: dict[str, str] = {}
    for sample in samples:
        path = DATASET_DIR / sample.dataset_version / sample.start.source_state
        actual = sha256(path)
        if actual != sample.start.source_sha256:
            raise ValueError(f"source hash mismatch: {sample.sample_id}")
        result[sample.sample_id] = actual
    return result


def pack(directory: Path, samples: list[EvalSample]) -> None:
    """备份旧起点后调用官方 pack；不连接用户共享服务，不删旧产物。"""
    directory.mkdir(parents=True, exist_ok=False)
    hashes = source_states(samples)
    shutil.copytree(DATASET_DIR / "v1/archives", directory / "archives_before")
    with capture_services(directory / "pack_services") as environment:
        process = start_process(
            ["-m", "evals.agent_short_goal_run.dataset.build.pack"],
            directory / "pack.log",
            environment,
        )
        try:
            if process.wait(timeout=600):
                raise RuntimeError("pack failed; see pack.log")
        finally:
            stop_process(process)
    manifests: dict[str, str] = {}
    for sample in samples:
        path = DATASET_DIR / "v1/archives" / sample.sample_id / "manifest.json"
        manifest = json.loads(path.read_text("utf-8"))
        if manifest["code"]["state_schema_hash"] != state_schema_hash():
            raise RuntimeError(f"schema mismatch: {sample.sample_id}")
        manifests[sample.sample_id] = sha256(path)
    write_record(
        directory / "pack_report.json",
        PackReport(
            git_head=git_head(),
            schema_hash=state_schema_hash(),
            source_hashes=hashes,
            archive_hashes=manifests,
            configuration_sha256=sha256(REPO_ROOT / "evals/config.json"),
            code_sha256=code_sha256(),
        ),
    )
    print("PACK_COMPLETE", len(manifests), flush=True)


def capture_one(directory: Path, sample: EvalSample) -> CaseReport:
    """一组专用服务、一 worker；硬终止保留起点、pending 与异常账。"""
    work = directory / "runs" / sample.sample_id
    error = ""
    with capture_services(directory / "services" / sample.sample_id) as environment:
        process = start_process(
            ["-m", "evals.common.capture_case", "--sample", sample.sample_id, "--out", str(work)],
            directory / "logs" / f"{sample.sample_id}.log",
            environment,
        )
        try:
            exit_code = process.wait(timeout=float(load_config()["timeout"]) + 120)
        except subprocess.TimeoutExpired:
            error, exit_code = "worker hard timeout", -1
        finally:
            stop_process(process)
    result_path = work / "run_result.json"
    return CaseReport(
        sample_id=sample.sample_id,
        git_head=git_head(),
        exit_code=exit_code,
        error=error,
        audit=audit_capture(work),
        run_result=RunResult.model_validate_json(result_path.read_text("utf-8"))
        if result_path.exists()
        else None,
    )


def capture(directory: Path, samples: list[EvalSample]) -> None:
    """只消费本批新起点；每样本前核提交、配置和来源，逐例原子留报告。"""
    report = PackReport.model_validate_json((directory / "pack_report.json").read_text("utf-8"))
    summary = BatchReport()
    if report.source_hashes != source_states(samples):
        raise RuntimeError("source states changed after pack")
    try:
        for number, sample in enumerate(samples, 1):
            if git_head() != report.git_head:
                raise RuntimeError("HEAD changed during capture")
            if code_sha256() != report.code_sha256:
                raise RuntimeError("runtime code or prompts changed during capture")
            if sha256(REPO_ROOT / "evals/config.json") != report.configuration_sha256:
                raise RuntimeError("configuration changed during capture")
            manifest = DATASET_DIR / "v1/archives" / sample.sample_id / "manifest.json"
            if sha256(manifest) != report.archive_hashes[sample.sample_id]:
                raise RuntimeError("start archive changed during capture")
            print("SAMPLE_START", number, len(samples), sample.sample_id, flush=True)
            result = capture_one(directory, sample)
            write_record(directory / "reports" / f"{sample.sample_id}.json", result)
            summary.completed.append(result)
            print("SAMPLE_END", result.model_dump_json(exclude={"run_result", "audit"}), flush=True)
            if result.audit.missing_from_recording or result.audit.missing_from_trace:
                raise RuntimeError("model-call recording/trace mismatch; inspect report")
            if code_sha256() != report.code_sha256 or git_head() != report.git_head:
                raise RuntimeError("runtime version changed inside a sample")
    except BaseException as error:
        summary.error = f"{type(error).__name__}: {error}"
        raise
    finally:
        write_record(directory / "batch_report.json", summary)


def main() -> None:
    """显式选择重打或采集；导入不启动服务、不调用模型。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["pack", "capture"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    load_env_file()
    samples = load_samples(CAPTURE_DATASET_VERSION)
    if len(samples) != 20:
        raise ValueError("expected exactly twenty frozen samples")
    directory = args.out.resolve()
    if args.phase == "pack":
        pack(directory, samples)
    else:
        (directory / "reports").mkdir(parents=True, exist_ok=False)
        capture(directory, samples)


if __name__ == "__main__":
    main()
