"""采集脚本用法：原子状态、带 token 的停止、完整等待和未完成询问。"""

import ctypes
import json
import os
import time
from ctypes import wintypes
from types import SimpleNamespace

import pytest
from _harness_fixtures.harness import GOAL, build_fake

from evals.common.brain_capture import record_brain_calls
from evals.common.capture_audit import audit_capture
from evals.common.capture_batch import CaseReport
from evals.common.capture_control import launch
from evals.common.capture_review import audit_review
from evals.common.capture_services import start_process, stop_process
from evals.common.capture_state import ControlState, read_state, save_state
from evals.common.capture_worker import recover_completed, stopped
from evals.common.invocation import write_record


def test_control_state_is_atomic_and_stop_only_accepts_the_current_token(tmp_path) -> None:
    state = ControlState(token="current", status="running")
    save_state(tmp_path, state)
    (tmp_path / "stop.request").write_text("stale", encoding="ascii")

    assert not stopped(tmp_path, state)
    (tmp_path / "stop.request").write_text("current", encoding="ascii")
    assert stopped(tmp_path, state)

    assert read_state(tmp_path).status == "stopped"
    assert not list(tmp_path.glob("*.tmp"))


def test_start_preserves_existing_outputs_and_resume_keeps_attempt_history(
    tmp_path, monkeypatch
) -> None:
    import evals.common.capture_control as control

    launches = []

    def start(arguments, log, environment):
        launches.append(arguments)
        return SimpleNamespace(pid=123)

    monkeypatch.setattr(control, "start_process", start)
    directory = tmp_path / "batch"
    original = launch(directory)
    with pytest.raises(FileExistsError):
        launch(directory)
    with pytest.raises(ValueError, match="stopped or failed"):
        launch(directory, resume=True)
    original.status, original.attempts = "failed", {"case": 1}
    save_state(directory, original)

    resumed = launch(directory, resume=True)

    assert resumed.token != original.token and resumed.attempts == {"case": 1}
    assert len(launches) == 2


def test_recording_a_real_fake_run_accounts_for_all_model_and_review_waits(tmp_path) -> None:
    fake = build_fake(tmp_path)
    record_brain_calls(fake.run_rt, tmp_path / "brain_calls")

    fake.harness.run("r1", [GOAL])

    calls, waits = audit_capture(tmp_path), audit_review(tmp_path)
    assert calls.missing_from_recording == calls.missing_from_trace == 0
    assert waits.requested == waits.completed == waits.trace_marks
    assert waits.pending == waits.failed == waits.missing == 0
    assert waits.trace_wait_s >= 0 and waits.port_elapsed_s >= 0
    assert "run/inject" in waits.by_port and "episode/inject" in waits.by_port


def test_a_pending_reviewer_request_is_not_reported_as_zero_wait_or_completed(tmp_path) -> None:
    port = tmp_path / "review_calls" / "episode" / "inject"
    port.mkdir(parents=True)
    (port / "000001.request.json").write_text(json.dumps({"round": 1}), encoding="utf-8")

    waits = audit_review(tmp_path)

    assert waits.requested == waits.pending == 1
    assert waits.completed == waits.trace_marks == 0


def test_resume_recovers_a_completed_report_without_repeating_the_case(tmp_path) -> None:
    work = tmp_path / "case"
    fake = build_fake(work)
    record_brain_calls(fake.run_rt, work / "brain_calls")
    result = fake.harness.run("r1", [GOAL])
    report = CaseReport(
        sample_id="case",
        git_head="fixed",
        exit_code=0,
        work_directory=str(work),
        audit=audit_capture(work),
        run_result=result,
    )
    (tmp_path / "reports").mkdir()
    write_record(tmp_path / "reports/case.json", report)
    state = ControlState(token="resume", status="running")

    assert recover_completed(tmp_path, "case", state)
    assert recover_completed(tmp_path, "case", state)

    assert state.completed == ["case"]
    assert read_state(tmp_path).completed == ["case"]


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher process tree")
def test_stopping_an_owned_worker_also_stops_its_child_process(tmp_path) -> None:
    code = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "creationflags=subprocess.CREATE_NO_WINDOW); "
        "print(child.pid,flush=True); time.sleep(60)"
    )
    log = tmp_path / "worker.log"
    process = start_process(["-c", code], log, dict(os.environ))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    child_handle = None
    try:
        deadline = time.monotonic() + 20
        while not log.read_text("utf-8").strip() and time.monotonic() < deadline:
            time.sleep(0.05)
        child_pid = int(log.read_text("utf-8").strip())
        child_handle = kernel.OpenProcess(0x100000, False, child_pid)
        assert child_handle

        stop_process(process)

        assert process.poll() is not None
        assert kernel.WaitForSingleObject(child_handle, 5000) == 0
    finally:
        stop_process(process)
        if child_handle:
            kernel.CloseHandle(child_handle)
