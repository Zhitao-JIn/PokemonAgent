"""将审阅旁账合成评分参考；生成器始终接收冻结原请求。"""

from evals.dataset.brain_calls.dataset_contract import ReferenceCase

from .contract import Annotation


def combine(reference: ReferenceCase, annotation: Annotation) -> ReferenceCase:
    """调用方保证已核验同一身份且有标签；排除项不允许合成可评分参考。"""
    assert reference.case_id == annotation.case_id and annotation.status == "labelled"
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
