"""将审阅旁账合成评分参考；生成器始终接收冻结原请求。"""

from evals.dataset.brain_calls.dataset_contract import ReferenceCase

from .contract import Annotation


def combine(reference: ReferenceCase, annotation: Annotation) -> ReferenceCase:
    """调用方保证已核验同一身份且有标签；排除项不允许合成可评分参考。"""
    assert reference.case_id == annotation.case_id and annotation.status == "labelled"
    if annotation.evaluation_mode == "advisory":
        return advisory_reference(reference, annotation)
    if annotation.method == "mechanical_preexisting":
        return reference
    constraints = dict(reference.constraints)
    constraints.update(
        {
            "review_method": annotation.method,
            "review_rationale": annotation.rationale,
        }
    )
    if annotation.acceptable:
        constraints["acceptable"] = [
            item.model_dump(exclude_none=True) for item in annotation.acceptable
        ]
        constraints["label_reason"] = annotation.rationale
    return reference.model_copy(
        update={
            "achieved": annotation.achieved,
            "evaluation": "action_set" if annotation.acceptable else reference.evaluation,
            "criteria": annotation.criteria or reference.criteria,
            "constraints": constraints,
            "evidence": [item.pointer for item in annotation.evidence],
            "mechanical_reason": annotation.rationale,
            "label_source": "mechanical"
            if annotation.method == "mechanical_preexisting"
            else "history_adjudicated",
        }
    )


def advisory_reference(reference: ReferenceCase, annotation: Annotation) -> ReferenceCase:
    """建议方案不构成答案白名单；原场景里程碑不升级成必须匹配的标准。"""
    return reference.model_copy(
        update={
            "evaluation": "source_grounded_rubric",
            "achieved": None,
            "check_id": None,
            "label_source": "history_adjudicated",
            "criteria": annotation.criteria,
            "evidence": [item.pointer for item in annotation.evidence],
            "constraints": {
                "semantic_grading": "advisory_v1",
                "reference_role": "non_exhaustive_suggestions",
                "case_context": annotation.rationale,
                "suggested_actions": [
                    item.model_dump(exclude_none=True) for item in annotation.acceptable
                ],
                "advisory_examples": annotation.suggestions,
                "precedence": (
                    "实际生产请求、当前观测和同请求历史优先于参考建议；允许其他有据可核的等价方案。"
                ),
            },
        }
    )
