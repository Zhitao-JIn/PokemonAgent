"""发布逐例审阅旁账；原始 v1 输入、参考与 baseline 均不改写。"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from evals.dataset.brain_calls import load_inputs, load_references
from evals.dataset.brain_calls.dataset_contract import InputCase, ReferenceCase
from evals.dataset.brain_calls.loader import directory_for

from . import choose_review, judge_review, planning_review
from .contract import Annotation
from .evidence import collect

ROOT = Path(__file__).resolve().parent
FAMILIES = ("choose", "judge", "plan", "decompose")


def annotate(case: InputCase, reference: ReferenceCase) -> Annotation:
    """保留原有机械标签的来源；其余由逐例审阅给出答案或排除理由。"""
    if reference.evaluation in {"mechanical", "action_set"}:
        return Annotation(
            case_id=case.case_id,
            family=case.family,
            request_sha256=case.source.request_canonical_sha256,
            status="labelled",
            method="mechanical_preexisting",
            rationale=(
                reference.mechanical_reason or str(reference.constraints.get("label_reason"))
            ),
            evidence=collect(case),
            achieved=reference.achieved,
            acceptable=reference.constraints.get("acceptable", []),
        )
    if case.family in {"plan", "decompose"}:
        return planning_review.review(case)
    if case.family == "choose":
        return choose_review.review(case)
    achieved, rationale = judge_review.review(case)
    return Annotation(
        case_id=case.case_id,
        family="judge",
        request_sha256=case.source.request_canonical_sha256,
        status="labelled",
        method="codex_history_review",
        rationale=rationale,
        evidence=collect(case),
        achieved=achieved,
    )


def build(version: str = "v1") -> None:
    """新目录只创建一次；失败中止，禁止覆盖既有冻结审阅版本。"""
    output = ROOT / version
    output.mkdir(exist_ok=False)
    manifests: dict[str, object] = {}
    for family in FAMILIES:
        cases, references = load_inputs(family), load_references(family)
        assert [case.case_id for case in cases] == [ref.case_id for ref in references]
        rows = [annotate(case, ref) for case, ref in zip(cases, references, strict=True)]
        path = output / f"{family}.jsonl"
        path.write_text(
            "".join(row.model_dump_json() + "\n" for row in rows), "utf-8", newline="\n"
        )
        _, source = directory_for(family, "v1")
        manifests[family] = {
            "cases": len(rows),
            "status": dict(Counter(row.status for row in rows)),
            "method": dict(Counter(row.method for row in rows)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "inputs_sha256": source.files_sha256["inputs.jsonl"],
        }
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "collection_version": "v1",
                "families": manifests,
                "baseline_answers_used": False,
                "reviewer": "codex_history_review",
                "policy": (
                    "Only the exact request context. Mechanical labels retain"
                    "ed with provenance. Exclusions outside score denominator"
                    ". Planning labels are case-specific rubrics, not unique "
                    "gold plans. Action sets are conservative reviewed altern"
                    "atives, not an exhaustive strategy space."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        "utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    build()
