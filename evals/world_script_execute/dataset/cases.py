"""完整脚本运行记录与独立期望组成 DeepEval 用例。"""

from deepeval.test_case import LLMTestCase

from ..isolated import run_isolated
from . import ScriptCase


def build_cases(cases: list[ScriptCase], version: str) -> list[LLMTestCase]:
    """每条用例顺序跑一个子进程；结果顺序与冻结用例顺序一致。"""
    runs = [run_isolated(case, version) for case in cases]
    return [
        LLMTestCase(
            name=case.case_id,
            input=f"{case.script}({', '.join(f'{k}={v!r}' for k, v in case.args.items())})",
            actual_output=run.model_dump_json(),
            expected_output=case.model_dump_json(),
        )
        for case, run in zip(cases, runs, strict=True)
    ]
