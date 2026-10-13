"""单用例子进程；只经类型化 JSON 收请求并落盘结果。"""

import sys

from .isolated import ScriptRequest
from .solver import run_case


def main() -> None:
    """执行请求；装配失败直接使进程失败，脚本异常由内核记入 crash。"""
    request = ScriptRequest.model_validate_json(sys.stdin.read())
    run = run_case(request.case, request.version, checkpoint=request.checkpoint)
    request.output.write_text(run.model_dump_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
