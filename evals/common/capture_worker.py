"""控制器的单写入 worker：固定版本，顺序打包、采集、审计与导出。"""

import argparse
import os
import subprocess
from pathlib import Path
from shutil import disk_usage

from evals.agent_short_goal_run.dataset.loader import DATASET_DIR, load_samples
from evals.common.capture_audit import audit_capture
from evals.common.capture_batch import (
    BatchReport,
    CaseReport,
    PackReport,
    code_sha256,
    git_head,
    sha256,
    source_states,
)
from evals.common.capture_configuration import capture_budget
from evals.common.capture_integrity import audit_batch
from evals.common.capture_pack import pack_sample, payload_paths
from evals.common.capture_review import audit_review
from evals.common.capture_services import capture_services, start_process, stop_process
from evals.common.capture_state import ControlState, read_state, save_state
from evals.common.invocation import write_record
from evals.paths import REPO_ROOT
from evals.runconfig import load_config, resolve_models
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.env import load_env_file
from pokemon_agent.harness.checkpoint.manifest import state_schema_hash
from pokemon_agent.schemas.harness.domain import RunResult


def fixed_version(directory: Path) -> PackReport:
    """校验固定代码、配置、schema 与来源；漂移立即阻止继续执行。"""
    path = directory / "pack_report.json"
    if path.exists():
        report = PackReport.model_validate_json(path.read_text("utf-8"))
        if (
            report.git_head,
            report.code_sha256,
            report.configuration_sha256,
            report.schema_hash,
        ) != (
            git_head(),
            code_sha256(),
            sha256(REPO_ROOT / "evals/config.json"),
            state_schema_hash(),
        ):
            raise RuntimeError("capture version or configuration drift")
        if report.source_hashes != source_states(load_samples()):
            raise RuntimeError("capture source states changed")
        if report.effective_budget != capture_budget():
            raise RuntimeError("capture effective budget changed")
        if report.sample_sha256 != sha256(DATASET_DIR / "v1/samples.jsonl"):
            raise RuntimeError("capture sample definitions changed")
        for path, expected in report.archive_payload_hashes.items():
            if sha256(directory / path) != expected:
                raise RuntimeError("capture archive payload changed")
        return report
    raise FileNotFoundError(path)


def preflight(directory: Path) -> None:
    """先固定二十例来源和已提交代码，不输出密钥值。"""
    samples = load_samples()
    if len(samples) != 20:
        raise ValueError("expected twenty source samples")
    models = resolve_models(load_config()["models"])
    BrainTool.build(
        text=models["text_model"],
        judge=models["judge_model"],
        verify=models["verify_model"],
        plan=models["plan_model"],
    )
    if disk_usage(directory).free < 2 * 1024**3:
        raise RuntimeError("capture requires at least 2 GiB free space")
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", "pokemon_agent", "evals"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    report = PackReport(
        effective_budget=capture_budget(),
        sample_sha256=sha256(DATASET_DIR / "v1/samples.jsonl"),
        archive_root=str(directory / "archives"),
        git_head=git_head(),
        schema_hash=state_schema_hash(),
        source_hashes=source_states(samples),
        archive_hashes={},
        configuration_sha256=sha256(REPO_ROOT / "evals/config.json"),
        code_sha256=code_sha256(),
    )
    write_record(directory / "pack_report.json", report)


def pack(directory: Path, state: ControlState) -> None:
    """每起点单独打包；恢复只跳过哈希已核对的完整存档。"""
    for sample in load_samples():
        report = fixed_version(directory)
        if sample.sample_id in report.archive_hashes:
            manifest = directory / "archives" / sample.sample_id / "manifest.json"
            if sha256(manifest) != report.archive_hashes[sample.sample_id]:
                raise RuntimeError("packed manifest changed")
            continue
        if stopped(directory, state):
            return
        manifest_path = pack_sample(directory, state, sample.sample_id)
        report.archive_payload_hashes.update(
            {p.relative_to(directory).as_posix(): sha256(p) for p in payload_paths(manifest_path)}
        )
        report.archive_hashes[sample.sample_id] = sha256(
            directory / "archives" / sample.sample_id / "manifest.json"
        )
        _replace_report(directory, report)


def _replace_report(directory: Path, report: PackReport) -> None:
    """原子更新已打包起点，保留固定版本与来源。"""
    temporary = directory / "pack_report.tmp"
    temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    os.replace(temporary, directory / "pack_report.json")


def stopped(directory: Path, state: ControlState) -> bool:
    """只接受当前 worker token 的停止请求。"""
    path = directory / "stop.request"
    if path.exists() and path.read_text("ascii") == state.token:
        state.status = "stopped"
        save_state(directory, state)
        return True
    return False


def run_case(directory: Path, sample_id: str, attempt: int) -> CaseReport:
    """独立服务与 worker；业务失败仍有结算，基础设施异常不冒充完成。"""
    work = directory / "runs" / f"attempt{attempt}" / sample_id
    error = ""
    with capture_services(directory / "services" / f"attempt{attempt}" / sample_id) as environment:
        process = start_process(
            [
                "-m",
                "evals.common.capture_case",
                "--sample",
                sample_id,
                "--out",
                str(work),
                "--archive-root",
                str(directory / "archives"),
            ],
            directory / "logs" / f"{sample_id}.attempt{attempt}.log",
            environment,
        )
        try:
            exit_code = process.wait(timeout=float(load_config()["timeout"]) + 120)
        except subprocess.TimeoutExpired:
            error, exit_code = "interrupted: worker hard timeout", -1
        finally:
            stop_process(process)
    result = work / "run_result.json"
    audit, waits = audit_capture(work), audit_review(work)
    write_record(work / "review_wait_report.json", waits)
    if waits.pending or waits.failed or waits.missing:
        error = error or "review waiting audit incomplete"
    return CaseReport(
        sample_id=sample_id,
        git_head=git_head(),
        exit_code=exit_code,
        error=error,
        audit=audit,
        work_directory=str(work),
        interrupted=exit_code == -1,
        run_result=RunResult.model_validate_json(result.read_text("utf-8"))
        if result.exists()
        else None,
    )


def recover_completed(directory: Path, sample_id: str, state: ControlState) -> bool:
    """核对已落盘报告，恢复报告与状态两次原子写入间的中断。"""
    path = directory / "reports" / f"{sample_id}.json"
    if not path.exists():
        if sample_id in state.completed:
            raise RuntimeError("completed case report missing")
        return False
    completed = CaseReport.model_validate_json(path.read_text("utf-8"))
    if completed.sample_id != sample_id or completed.error or completed.exit_code:
        raise RuntimeError("completed case report invalid")
    if completed.run_result is None:
        raise RuntimeError("completed case result missing")
    work = Path(completed.work_directory)
    checked, waits = audit_capture(work), audit_review(work)
    if checked != completed.audit or waits.pending or waits.failed or waits.missing:
        raise RuntimeError("completed case evidence changed")
    if sample_id not in state.completed:
        state.completed.append(sample_id)
        save_state(directory, state)
    return True


def capture(directory: Path, state: ControlState) -> None:
    """完成一例才落审计报告；失败尝试保留，resume 使用新 attempt。"""
    for sample in load_samples():
        report = fixed_version(directory)
        manifest = directory / "archives" / sample.sample_id / "manifest.json"
        if sha256(manifest) != report.archive_hashes[sample.sample_id]:
            raise RuntimeError("archive drift")
        if recover_completed(directory, sample.sample_id, state):
            continue
        if stopped(directory, state):
            return
        state.current_sample = sample.sample_id
        attempt = state.attempts.get(sample.sample_id, 0) + 1
        state.attempts[sample.sample_id] = attempt
        save_state(directory, state)
        result = run_case(directory, sample.sample_id, attempt)
        history = directory / "reports_history"
        history.mkdir(exist_ok=True)
        write_record(history / f"{sample.sample_id}.attempt{attempt}.json", result)
        coverage = result.audit
        if (
            result.error
            or result.exit_code
            or result.run_result is None
            or coverage.missing_from_recording
            or coverage.missing_from_trace
            or any(p.pending for p in coverage.ports.values())
        ):
            raise RuntimeError(
                f"case infrastructure/audit failure: {sample.sample_id}; see reports_history"
            )
        fixed_version(directory)
        (directory / "reports").mkdir(exist_ok=True)
        write_record(directory / "reports" / f"{sample.sample_id}.json", result)
        state.completed.append(sample.sample_id)
        save_state(directory, state)


def export(directory: Path, state: ControlState) -> None:
    """审计全部完成后只导出原料；标注、公开版本和真实评分另行处理。"""
    from evals.dataset.brain_calls.export_dataset import export as export_dataset
    from evals.dataset.brain_calls.source_archive import archive_sources
    from evals.dataset.brain_calls.verify_dataset import verify

    reports = [
        CaseReport.model_validate_json(p.read_text("utf-8"))
        for p in sorted((directory / "reports").glob("*.json"))
    ]
    if len(reports) != 20 or len(state.completed) != 20:
        raise RuntimeError("cannot export incomplete batch")
    batch_path = directory / "batch_report.json"
    expected = BatchReport(completed=reports)
    if batch_path.exists():
        if BatchReport.model_validate_json(batch_path.read_text("utf-8")) != expected:
            raise RuntimeError("completed batch report changed")
    else:
        write_record(batch_path, expected)
    number = state.attempts.get("export", 0) + 1
    state.attempts["export"] = number
    save_state(directory, state)
    output = directory / "exports" / f"attempt{number}" / "v2"
    export_dataset(directory, output)
    archive_sources(directory, output)
    verify(output)
    state.output = str(output)


def audit(directory: Path, state: ControlState) -> None:
    """脚本单独记录完整性阶段，不把采集完成等同于可发布。"""
    fixed_version(directory)
    audit_batch(directory)


def main() -> None:
    """单一 worker 控制所有阶段；失败原地落报告，不循环重试无限烧预算。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    directory = args.out.resolve()
    state = read_state(directory)
    if state.token != args.token:
        raise RuntimeError("worker token mismatch")
    state.pid, state.status = os.getpid(), "running"
    save_state(directory, state)
    load_env_file()
    try:
        if not (directory / "pack_report.json").exists():
            preflight(directory)
        for phase, operation in (
            ("pack", pack),
            ("capture", capture),
            ("audit", audit),
            ("export", export),
        ):
            state.phase = phase
            save_state(directory, state)
            operation(directory, state)
            if state.status == "stopped":
                return
        state.status, state.current_sample = "complete", None
    except BaseException as error:
        state.status, state.error = "failed", f"{type(error).__name__}: {error}"
        raise
    finally:
        save_state(directory, state)


if __name__ == "__main__":
    main()
