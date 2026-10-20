"""递归规划批次的标注旁账：机械标签保留，其余由作者表给出；建议式与二元式分别构建。"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from evals.dataset.brain_calls import load_inputs, load_references
from evals.dataset.brain_calls.dataset_contract import InputCase, ReferenceCase
from evals.dataset.brain_calls.loader import directory_for

from .advisory_build import criteria_for
from .authoring import Authored, load_authoring
from .contract import Annotation
from .evidence import collect

ROOT = Path(__file__).resolve().parent
FAMILIES = ("choose", "judge", "plan", "decompose")
MECHANICAL = {"mechanical", "action_set"}


def base(case: InputCase, status: str, rationale: str) -> dict[str, object]:
    """所有标注共有的字段；证据只取自请求。"""
    return {
        "case_id": case.case_id,
        "family": case.family,
        "request_sha256": case.source.request_canonical_sha256,
        "status": status,
        "method": "codex_history_review",
        "rationale": rationale,
        "evidence": collect(case),
    }


def judge_annotation(
    case: InputCase, reference: ReferenceCase, authored: Authored | None
) -> Annotation:
    """机械标签保留来源；其余按作者表，排除项不计分母。"""
    if reference.evaluation in MECHANICAL:
        fields = base(case, "labelled", reference.mechanical_reason or "mechanical")
        fields["method"] = "mechanical_preexisting"
        decision = "achieved" if reference.achieved else None
        return Annotation(**fields, achieved=reference.achieved, expected_decision=decision)
    assert authored is not None
    fields = base(case, authored.status, authored.rationale)
    if authored.status != "labelled":
        return Annotation(**fields)
    return Annotation(
        **fields, achieved=authored.achieved, expected_decision=authored.expected_decision
    )


def advisory_annotation(
    case: InputCase, reference: ReferenceCase, authored: Authored
) -> Annotation | None:
    """choose/plan/decompose 的建议式旁账；机械动作集合并入可接受动作。"""
    if authored.status != "labelled":
        return Annotation(**base(case, authored.status, authored.rationale))
    acceptable = (
        reference.constraints.get("acceptable", []) if reference.evaluation in MECHANICAL else []
    )
    fields = base(case, "labelled", authored.rationale)
    return Annotation(
        **fields,
        evaluation_mode="advisory",
        acceptable=acceptable if case.family == "choose" else [],
        criteria=criteria_for(case),
        suggestions=authored.suggestions or [authored.rationale],
    )


def annotate(
    case: InputCase, reference: ReferenceCase, authored: Authored | None
) -> Annotation | None:
    """按家族分派；返回的每条都已通过 Annotation 契约校验。"""
    if case.family == "judge":
        return judge_annotation(case, reference, authored)
    assert authored is not None
    return advisory_annotation(case, reference, authored)


def build(version: str) -> None:
    """新目录只创建一次；作者表缺登记或原料错位时失败，旧版本不被触碰。"""
    output = ROOT / version
    output.mkdir(exist_ok=False)
    manifests: dict[str, object] = {}
    for family in FAMILIES:
        cases, references = load_inputs(family, version), load_references(family, version)
        assert [c.case_id for c in cases] == [r.case_id for r in references]
        authored = load_authoring(version, family, [c.case_id for c in cases])
        rows = []
        for case, ref in zip(cases, references, strict=True):
            row = annotate(case, ref, authored.get(case.case_id))
            assert row is not None
            rows.append(row)
        path = output / f"{family}.jsonl"
        path.write_text(
            "".join(row.model_dump_json() + "\n" for row in rows), "utf-8", newline="\n"
        )
        _, source = directory_for(family, version)
        manifests[family] = {
            "cases": len(rows),
            "status": dict(Counter(row.status for row in rows)),
            "method": dict(Counter(row.method for row in rows)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "inputs_sha256": source.files_sha256["inputs.jsonl"],
            "authoring_sha256": hashlib.sha256(
                (ROOT / "authoring" / version / f"{family}.jsonl").read_bytes()
            ).hexdigest(),
        }
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "collection_version": version,
                "families": manifests,
                "baseline_answers_used": False,
                "reviewer": "codex_history_review",
                "policy": (
                    "Recursive-planning capture. Judge: mechanical labels kept with provenance, "
                    "others adjudicated from request-visible evidence only, "
                    "with expected_decision. "
                    "Choose/plan/decompose: advisory suggestions, AI quality grading, not gold."
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
    import sys

    build(sys.argv[1])
