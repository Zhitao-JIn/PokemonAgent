"""发布建议式参考：补救动作、多种等价选择和开放规划交给 AI 评分。"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from evals.dataset.brain_calls import load_inputs
from evals.dataset.brain_calls.dataset_contract import Criterion, InputCase
from evals.dataset.brain_calls.loader import directory_for
from evals.dataset.brain_choose.schemas import ActionMatcher

from .contract import Annotation, Evidence
from .loader import ROOT, load
from .recovery_options import recovery

VERSIONS: dict[str, str] = {"choose": "v4", "plan": "v3", "decompose": "v3"}


def criteria_for(case: InputCase) -> list[Criterion]:
    """维度评合理性，不要求命中建议中的动作、粒度或步骤顺序。"""
    pointers = [item.pointer for item in load_evidence(case)]
    dimensions = {
        "state_and_scope": (
            "符合实际目标、当前观测和本次可见历史；识别失效前提，不导入其他调用事实。"
        ),
        "progress_or_recovery": (
            "推进当前目标或给出有依据的失败恢复/有限探索；"
            "不要求一步成功或匹配参考建议，避免无效循环。"
            if case.family == "choose"
            else "方案能从当前状态推进目标，前置依赖、粒度和预算合理；"
            "允许不同拆分、顺序及等价方案。"
        ),
        "boundaries_and_history": (
            "遵守实际动作能力和请求边界；不越过只开菜单/只移动光标的目标，合理利用已有失败经验。"
            if case.family == "choose"
            else "遵守原请求的明确限制与已完成事实；不重复已完成任务，"
            "不伪造状态，不把建议路线当唯一答案。"
        ),
    }
    return [
        Criterion(name=name, instruction=instruction, evidence=pointers)
        for name, instruction in dimensions.items()
    ]


def load_evidence(case: InputCase) -> list[Evidence]:
    """证据仅来自当前请求；不读取模型响应或后续记录。"""
    from .evidence import collect

    return collect(case)


def annotate(case: InputCase, previous: Annotation) -> Annotation:
    """保留仍无动作表达的现场，其余用建议式参考替代穷尽动作集合。"""
    if (
        case.family == "choose"
        and case.case_id == "knowledge_battle_action_menu.task.choose.000003"
    ):
        return previous
    if case.family == "decompose" and previous.status != "labelled":
        return previous
    examples = previous.suggestions or [previous.rationale]
    options = previous.acceptable
    context = previous.rationale
    if case.family == "choose" and previous.status != "labelled":
        keys, context = recovery(case)
        options = [
            ActionMatcher(key=key, max_times=1) for key in keys if case.request.space.enabled(key)
        ]
        examples = [context]
    if case.family == "plan" and previous.status != "labelled":
        context = (
            "当前不在原战斗，而原目标明确禁止重新遇敌。可在 why/note 中说明无法同时满足的前提，"
            "放弃失效目标或要求恢复原现场；不能发明重新遇敌作为获准步骤。派发约束诊断与语义分分别呈现。"
        )
        examples = [context]
    return Annotation(
        case_id=case.case_id,
        family=case.family,
        request_sha256=case.source.request_canonical_sha256,
        status="labelled",
        method="codex_history_review",
        evaluation_mode="advisory",
        rationale=context,
        evidence=load_evidence(case),
        acceptable=options if case.family == "choose" else [],
        criteria=criteria_for(case),
        suggestions=examples,
    )


def write_json(path: Path, value: object) -> None:
    """调用方保证发布目录是新建的；按 LF 保证指纹可移植。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n")


def build(output: Path = ROOT / "v2") -> None:
    """新版本只创建一次；旧旁账和 judge 既有版本不改写。"""
    output.mkdir(exist_ok=False)
    manifests: dict[str, object] = {}
    for family in VERSIONS:
        cases, previous = load_inputs(family), load(family, "v1")
        assert [row.case_id for row in cases] == [row.case_id for row in previous]
        rows = [annotate(case, old) for case, old in zip(cases, previous, strict=True)]
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
    write_json(
        output / "manifest.json",
        {
            "version": "v2",
            "collection_version": "v1",
            "families": manifests,
            "baseline_answers_used": False,
            "reviewer": "codex_history_review",
            "policy": (
                "Advisory references, multiple valid actions and recovery allowed. "
                "AI quality grading, not an exhaustive whitelist. "
                "Judge remains on the unchanged v1 annotations/v4 task data."
            ),
        },
    )


def publish() -> None:
    """各能力清单固定源输入和建议式旁账的字节指纹。"""
    for family, version in VERSIONS.items():
        rows = load(family, "v2")
        directory = ROOT.parent / f"brain_{family}" / version
        directory.mkdir(exist_ok=False)
        _, source = directory_for(family, "v1")
        write_json(
            directory / "manifest.json",
            {
                "version": version,
                "family": family,
                "collection_version": "v1",
                "cases": len(rows),
                "inputs_sha256": source.files_sha256["inputs.jsonl"],
                "references_sha256": source.files_sha256["references.jsonl"],
                "annotation_version": "v2",
                "annotation_sha256": hashlib.sha256(
                    (ROOT / "v2" / f"{family}.jsonl").read_bytes()
                ).hexdigest(),
            },
        )
        write_json(
            directory / "coverage.json",
            {
                "source_cases": len(rows),
                "labelled": sum(row.status == "labelled" for row in rows),
                "excluded": [
                    {"case_id": row.case_id, "reason": row.rationale}
                    for row in rows
                    if row.status != "labelled"
                ],
                "reference_role": "non_exhaustive_suggestions",
                "baseline_answers_used_as_gold": False,
            },
        )


if __name__ == "__main__":
    build()
    publish()
