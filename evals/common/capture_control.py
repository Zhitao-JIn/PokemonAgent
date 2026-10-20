"""采集批次控制：start/status/stop/resume；不依赖交互监控。"""

import argparse
import os
from pathlib import Path
from uuid import uuid4

from evals.paths import REPO_ROOT

from .capture_services import start_process
from .capture_state import ControlState, read_state, save_state


def launch(directory: Path, *, resume: bool = False) -> ControlState:
    """启动单一隐藏 worker；恢复前必须已由原 worker 标记停止或失败。"""
    if resume:
        previous = read_state(directory)
        if previous.status not in ("stopped", "failed"):
            raise ValueError("resume requires a stopped or failed worker")
        state = previous.model_copy(
            update={"token": uuid4().hex, "status": "starting", "error": ""}
        )
        (directory / "stop.request").unlink(missing_ok=True)
    else:
        directory.mkdir(parents=True, exist_ok=False)
        state = ControlState(token=uuid4().hex)
    save_state(directory, state)
    process = start_process(
        ["-m", "evals.common.capture_worker", "--out", str(directory), "--token", state.token],
        directory / f"controller.{state.token}.log",
        {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONUNBUFFERED": "1"},
    )
    # 步骤 1：worker 写入自己的 PID，父进程不再覆盖 worker 状态。
    return state.model_copy(update={"pid": process.pid})


def main() -> None:
    """命令只有显式 start/resume 才启动模型与模拟器流水线。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "status", "stop", "resume"])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    directory = args.out.resolve()
    if args.command in ("start", "resume"):
        state = launch(directory, resume=args.command == "resume")
    else:
        state = read_state(directory)
        if args.command == "stop":
            if state.status not in ("running", "starting"):
                raise ValueError("batch is not running")
            (directory / "stop.request").write_text(state.token, encoding="ascii")
    print(state.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
