"""每例独立子进程，Windows 上保留 300 秒墙钟保护。"""

import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

from .dataset import ScriptCase
from .dataset.loader import DEFAULT_VERSION
from .solver import ScriptRun

SAMPLE_TIME_LIMIT = 300


class ScriptRequest(BaseModel):
    """子进程的输入与本次隔离输出路径。"""

    case: ScriptCase
    version: str
    output: Path
    checkpoint: Path


class ScriptSetupTimeout(RuntimeError):
    """尚未取得开跑帧即超时，无法构造可评分的脚本运行记录。"""


class ScriptWorkerFailure(RuntimeError):
    """模拟器装配或取帧失败；脚本自身异常由 ScriptRun.crash 承载。"""


def run_isolated(
    case: ScriptCase, version: str = DEFAULT_VERSION, *, timeout: float = SAMPLE_TIME_LIMIT
) -> ScriptRun:
    """起一个 worker；超时由 subprocess 杀掉并回收，装配错误上抛。

    调用方保证 timeout 为正；取得开跑帧后超时返回 crash=超时，未取得则抛专名异常。
    """
    assert timeout > 0
    root = Path.cwd() / "eval_results"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="script-") as directory:
        request = ScriptRequest(
            case=case,
            version=version,
            output=Path(directory) / "result.json",
            checkpoint=Path(directory) / "before.json",
        )
        try:
            process = subprocess.run(
                [sys.executable, "-m", "evals.world_script_execute.worker"],
                input=request.model_dump_json(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            if not request.checkpoint.is_file():
                raise ScriptSetupTimeout(f"{case.case_id}: 装配超时") from error
            run = ScriptRun.model_validate_json(request.checkpoint.read_text(encoding="utf-8"))
            return run.model_copy(update={"seconds": float(timeout)})
        if process.returncode:
            raise ScriptWorkerFailure(f"{case.case_id}: {process.stderr}")
        return ScriptRun.model_validate_json(request.output.read_text(encoding="utf-8"))
