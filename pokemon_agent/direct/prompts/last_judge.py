"""「上一次本层判定」这段素材的渲染：`decompose` 与 `run_plan` 共用一个真源。

素材是 `JudgeFeedback`（判定员怎么判的、人认没认、人的理由）；怎么用它的规则写在各自模板里。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness.domain import AuditVerdict, JudgeFeedback


def last_judge_lines(feedback: JudgeFeedback) -> list[str]:
    """渲成素材行：判定员的结论与理由；被人推翻时再加一行人的理由。"""
    said = feedback.decision
    lines = [f"- 判定员说：{said}——{feedback.why}"]
    if feedback.audit is AuditVerdict.OVERTURN:
        lines.append(f"- 人推翻了这个判定：{feedback.note or '（没给理由）'}")
    return lines


__all__ = ["last_judge_lines"]
