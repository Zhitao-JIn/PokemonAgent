"""choose 模块启动也交给 Inspect，与四个独立脑能力任务入口保持一致。"""

import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """透传 Inspect eval 参数并返回原退出码；不自行调用模型或旧 DeepEval 运行器。"""
    task = Path(__file__).resolve().with_name("task.py")
    arguments = list(sys.argv[1:] if argv is None else argv)
    return subprocess.call([sys.executable, "-m", "inspect_ai", "eval", str(task), *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
