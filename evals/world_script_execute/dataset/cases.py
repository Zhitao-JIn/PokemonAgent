"""完整脚本运行记录与独立期望组成 DeepEval 用例。"""

from concurrent.futures import ThreadPoolExecutor

from deepeval.test_case import LLMTestCase

from ..isolated import run_isolated
from . import ScriptCase


def build_cases(cases: list[ScriptCase], version: str, workers: int = 1) -> list[LLMTestCase]:
    """每条用例一个子进程；结果顺序与冻结用例顺序一致。"""
    assert workers > 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(lambda case: run_isolated(case, version), cases))
    return [
        LLMTestCase(
            name=case.case_id,
            input=f"{case.script}({', '.join(f'{k}={v!r}' for k, v in case.args.items())})",
            actual_output=run.model_dump_json(),
            expected_output=case.model_dump_json(),
        )
        for case, run in zip(cases, runs, strict=True)
    ]
