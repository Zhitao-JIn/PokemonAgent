"""应用逐条 RAM 审核决定，保存证据；局部按键结论不冒充完整动作集合或人工审核。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from evals.dataset.brain_choose_action.build.from_capture import (
    EVALUATION_SCENES,
    CaptureRow,
    read_request,
)
from evals.dataset.brain_choose_action.schemas import ActionMatcher, ChooseCase
from evals.dataset.io import contained_file
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.world.interface.domain.ram_readout import RamReadout


class Decision(BaseModel):
    """显式逐条决定；local_supported 只承诺下一键，其他结论不得带评分标签。"""

    case_id: str
    verdict: Literal["local_supported", "goal_conflict", "insufficient_evidence", "outside_scope"]
    keys: list[str] = Field(default_factory=list)
    script_candidates: list[ActionMatcher] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_decision(self) -> Decision:
        """外部审核决定缺标签或把不确定项当标签时明确拒绝。"""
        if (self.verdict == "local_supported") != bool(self.keys):
            raise ValueError("只有 local_supported 可以且必须带非空 keys")
        if self.verdict != "local_supported" and self.script_candidates:
            raise ValueError("未确定下一键的记录不附脚本候选")
        if any(item.script is None for item in self.script_candidates):
            raise ValueError("script_candidates 只能含脚本")
        return self


class ReviewEvidence(BaseModel):
    """证据来自同帧 sense/RAM 与原始请求，不消费 chooser 响应和执行动作。"""

    batch: str
    request_path: str
    context_path: str
    request_sha256: str
    context_sha256: str
    frame_sha256: str
    ram: RamReadout
    where: str
    facing: str
    overlay: str
    walk_map: str
    screen: str
    option_layout: str


class ReviewedRecord(BaseModel):
    """助手核对记录；full_action_set_verified 为假，禁止作为正式评测批准。"""

    decision: Decision
    scene: str
    goal: str
    criteria: str
    evidence: ReviewEvidence
    reviewer: Literal["codex_ram_review"] = "codex_ram_review"
    full_action_set_verified: Literal[False] = False
    limitation: str = (
        "只核定局部下一键；脚本候选未经执行验证、参数集合不完备，"
        "不生成 human 标签、不冻结、不用于完整 choose 正式评分。"
    )


def evidence_for(batch: Path, row: CaptureRow) -> ReviewEvidence:
    """保留同帧 RAM 原值和内容摘要；来源路径不存在或越界立即失败。"""
    request_path = contained_file(batch, row.request)
    context_path = contained_file(batch, row.context)
    sense = json.loads(context_path.read_text(encoding="utf-8"))["sense_event"]["content"]
    facts = sense["facts"]
    return ReviewEvidence(
        batch=str(batch),
        request_path=row.request,
        context_path=row.context,
        request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),
        context_sha256=hashlib.sha256(context_path.read_bytes()).hexdigest(),
        frame_sha256=hashlib.sha256(sense["frame"].encode()).hexdigest(),
        ram=RamReadout.model_validate(sense["ram"]),
        where=facts["where"],
        facing=facts["facing"],
        overlay=facts["overlay"],
        walk_map=facts["walk_map"],
        screen=facts["screen"],
        option_layout=facts.get("option_layout", ""),
    )


def apply_review(
    source: Path, decisions: list[Decision]
) -> tuple[list[ReviewedRecord], list[ChooseCase]]:
    """每条来源恰有一个决定且动作在原 mask 中；任何缺失、重复或越权即失败。"""
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    by_id = {item.case_id: item for item in decisions}
    identifiers = [raw["case_id"] for raw in rows]
    if len(by_id) != len(decisions) or len(set(identifiers)) != len(identifiers):
        raise ValueError("来源或审核决定有重复 id")
    if set(by_id) != set(identifiers):
        raise ValueError("审核决定必须完整覆盖来源 id")
    records: list[ReviewedRecord] = []
    cases: list[ChooseCase] = []
    for raw in rows:
        row = CaptureRow(
            id=raw["case_id"],
            sample_id=raw["case_id"].split("/")[-2],
            scene=raw["scene"],
            task_goal=raw["goal"],
            task_criteria=raw["criteria"],
            request=raw["request"],
            context=raw["context"],
        )
        batch = Path(raw["batch"])
        req = read_request(batch, row)
        decision = by_id[row.id]
        if row.scene not in EVALUATION_SCENES and decision.verdict != "outside_scope":
            raise ValueError(f"{row.id}: 六类之外的场合只能存档")
        if any(not req.space.mask.get(key, False) for key in decision.keys):
            raise ValueError(f"{row.id}: 审核按键越权")
        if any(not req.space.mask.get(item.script, False) for item in decision.script_candidates):
            raise ValueError(f"{row.id}: 脚本候选越权")
        records.append(
            ReviewedRecord(
                decision=decision,
                scene=row.scene,
                goal=row.task_goal,
                criteria=row.task_criteria,
                evidence=evidence_for(batch, row),
            )
        )
        if decision.keys:
            cases.append(local_case(req, decision, f"{batch}/{row.request}", raw["version_limit"]))
    return records, cases


def local_case(
    req: FromHarnessToBrainToolChooseOnceReq, decision: Decision, origin: str, version_limit: str
) -> ChooseCase:
    """下一键候选仍用 rule 来源；不得冒充人工确认的完整动作集合。"""
    assert decision.verdict == "local_supported" and decision.keys
    return ChooseCase(
        case_id=decision.case_id,
        request=req,
        scene=req.obs.scene,
        acceptable=[ActionMatcher(key=key, max_times=1) for key in decision.keys],
        source="collected",
        label_source="rule",
        origin=origin,
        label_note=f"助手 RAM 局部审核：{decision.reason}。完整动作集合未审，禁止正式评分。"
        f"版本限制：{version_limit}",
    )


def summary(records: list[ReviewedRecord]) -> dict[str, object]:
    """汇总核对覆盖与未关闭事项，不计算模型分数。"""
    return {
        "reviewed": len(records),
        "verdicts": dict(Counter(row.decision.verdict for row in records)),
        "local_supported_scenes": dict(
            Counter(row.scene for row in records if row.decision.verdict == "local_supported")
        ),
        "full_action_set_verified": 0,
        "formal_evaluation_ready": False,
        "blockers": [
            "RAM 能证明输入状态和局部下一键，不能证明所有脚本参数的行为及完整策略正确性",
            "当前 ActionMatcher 仅支持参数子集相等，不能表达推进预算等参数的有效范围",
            "原始多段按键输出与 task 只执行首段一次的评分口径仍需明确",
            "旧批次采集代码版本限制保留，start_menu 与失败反馈/知识覆盖仍缺失",
        ],
    }
