"""接管用例并入 world_actions：共用 solver，保留原来独立的状态变化核对。"""

from __future__ import annotations

from typing import Any

from inspect_ai.dataset import Sample

from .schemas import ScriptCase, ScriptExpect, ScriptRun, ScriptVerdict
from .takeover_cases import CASES, ScriptStatus


def case_for(metadata: dict[str, Any]) -> ScriptCase:
    """从 sample 元数据恢复统一调用契约；未知 id 由 task 入口拒绝。"""
    return ScriptCase.model_validate(metadata["case"])


def takeover_samples() -> list[Sample]:
    """原接管用例变成 inspect 样本；id 加前缀避免与常规用例撞名。"""
    samples: list[Sample] = []
    for case in CASES:
        code = "ok" if case.status is ScriptStatus.DONE else (case.reason or case.status).value
        call = ScriptCase(
            case_id=f"takeover:{case.case_id}",
            state=case.state,
            pre=case.pre,
            script=case.script,
            args=case.args,
            basis="原接管用例的手写状态核对",
            expect=ScriptExpect(
                ok=case.status is ScriptStatus.DONE, code=code, takeover_id=case.case_id
            ),
        )
        samples.append(
            Sample(
                id=call.case_id,
                input=f"{call.script}({call.args})",
                target=code,
                metadata={
                    "script": call.script,
                    "case": call.model_dump(mode="json"),
                    "takeover_id": case.case_id,
                },
            )
        )
    return samples


def judge_takeover(case_id: str, run: ScriptRun) -> ScriptVerdict:
    """报告按原结局契约判，状态变化只读前后观测，不信脚本自述。"""
    case = next(c for c in CASES if c.case_id == case_id)
    problems: list[str] = []
    report = run.report
    code = "ok" if case.status is ScriptStatus.DONE else (case.reason or case.status).value
    if report is None:
        problems.append(run.crash)
    else:
        if report.code != code or report.data.get("status") != case.status.value:
            problems.append(f"结局不符：{report.code}/{report.data.get('status')}")
        if report.ok != (case.status is ScriptStatus.DONE):
            problems.append(f"ok={report.ok}")
        if case.summary and case.summary not in str(report.data.get("summary", "")):
            problems.append(f"摘要缺少 {case.summary!r}")
    truth: list[str] = []
    for check in case.checks:
        try:
            problem = check(run.before_observation, run.after_observation)
        except AssertionError as exc:
            problem = str(exc)
        if problem:
            truth.append(problem)
    return ScriptVerdict(code_problems=problems, truth_problems=truth)
