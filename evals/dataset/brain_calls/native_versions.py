"""把独立标签子集发布为已有 judge/choose 运行器可直接消费的新版本。"""

import hashlib
import json
from pathlib import Path

from evals.dataset.brain_choose.schemas import ChooseCase
from evals.dataset.brain_judge.schemas import JudgeEvidence, TruthMethod
from evals.dataset.brain_judge.schemas_v3 import JudgeCaseV3, JudgeOriginV3
from evals.paths import REPO_ROOT

from .dataset_contract import InputCase, ReferenceCase


def pairs(root: Path, family: str) -> list[tuple[InputCase, ReferenceCase]]:
    """按冻结顺序配对；错位为调用方违约，导出验证器负责外部数据核验。"""
    inputs = [
        InputCase.model_validate_json(line)
        for line in (root / family / "inputs.jsonl").read_text("utf-8").splitlines()
    ]
    refs = [
        ReferenceCase.model_validate_json(line)
        for line in (root / family / "references.jsonl").read_text("utf-8").splitlines()
    ]
    assert [case.case_id for case in inputs] == [ref.case_id for ref in refs]
    return list(zip(inputs, refs, strict=True))


def judge_case(
    case: InputCase, ref: ReferenceCase, truth_method: TruthMethod = "mechanical"
) -> JudgeCaseV3:
    """调用方保证独立标签已确定且有原始 trace 身份；来源方法必须如实填写。"""
    assert ref.achieved is not None and case.source.trace_uuids
    meta = case.source.meta
    return JudgeCaseV3(
        layer=case.layer,
        case_id=case.case_id,
        request=case.request,
        achieved=ref.achieved,
        goal_family=(
            "battle_or_encounter"
            if any(word in case.source.sample_id for word in ("battle", "catch", "wild"))
            else "navigation"
            if any(word in case.source.sample_id for word in ("door", "obstacle", "center_enter"))
            else "interaction"
        ),
        negative_mode=None if ref.achieved else "required_state_missing",
        truth_method=truth_method,
        check_id=ref.check_id,
        origin=JudgeOriginV3(
            branch=meta["branch"],
            source=meta["source"],
            run_id=meta["run_id"],
            episode_id=meta["episode_id"],
            task_id=meta["task_id"],
            step=meta["step"],
            trace_uuid=case.source.trace_uuids[0],
        ),
        request_sha256=case.source.request_canonical_sha256,
        evidence=[
            JudgeEvidence(
                source="production_input_or_trace_prefix",
                locator=locator,
                summary=ref.mechanical_reason,
            )
            for locator in ref.evidence
        ],
    )


def choose_case(case: InputCase, ref: ReferenceCase) -> ChooseCase:
    """调用方保证动作集合来自独立规则，非被测输出。"""
    assert ref.evaluation == "action_set" and ref.constraints["acceptable"]
    return ChooseCase(
        case_id=case.case_id,
        request=case.request,
        acceptable=ref.constraints["acceptable"],
        scene=case.request.obs.scene,
        tags=["answer_in_memory"] if case.request.memories else ["read_screen"],
        source="collected",
        label_source="rule",
        label_note=ref.constraints["label_reason"],
        origin=case.source.request_file,
    )


def publish(root: Path, family: str, output: Path, version: str) -> int:
    """只把有独立标签的子集计入分母；全量输入留在共享 collection。"""
    output.mkdir(parents=True, exist_ok=False)
    records, excluded = [], []
    for case, ref in pairs(root, family):
        eligible = (
            ref.achieved is not None and bool(case.source.trace_uuids)
            if family == "judge"
            else ref.evaluation == "action_set"
        )
        if eligible:
            records.append(judge_case(case, ref) if family == "judge" else choose_case(case, ref))
        else:
            excluded.append({"case_id": case.case_id, "reason": "independent_label_pending"})
    name = "dataset.jsonl" if family == "judge" else "cases.jsonl"
    with (output / name).open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(record.model_dump_json() + "\n")
    manifest = {
        "version": version,
        "dataset_file": name,
        "dataset_sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "coverage.json").write_text(
        json.dumps(
            {
                "labelled": len(records),
                "excluded": excluded,
                "source_collection": root.resolve().relative_to(REPO_ROOT).as_posix(),
                "baseline_answers_used_as_gold": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return len(records)
