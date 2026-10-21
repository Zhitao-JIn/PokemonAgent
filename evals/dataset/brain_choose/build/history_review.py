"""应用完整历史审核：动作集合可含按键与脚本，所有排除和保留均有逐条理由。"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from evals.dataset.brain_choose.build.from_capture import EVALUATION_SCENES
from evals.dataset.brain_choose.build.history_context import HistoryPacket
from evals.dataset.brain_choose.schemas import ActionMatcher, ChooseCase


class Annotation(BaseModel):
    """助手根据完整请求形成的显式决定，不把模型响应或未来轨迹当标签。"""

    case_id: str
    status: Literal["eligible", "excluded", "unresolved", "outside_scope"]
    acceptable: list[ActionMatcher] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    cited_history_steps: list[int] = Field(default_factory=list)
    tags: list[Literal["read_screen", "answer_in_memory", "after_failure"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def check_annotation(self) -> Annotation:
        """只有可用现场带非空可接受集合；排除项不得带伪造答案。"""
        if (self.status == "eligible") != bool(self.acceptable):
            raise ValueError("仅 eligible 可以且必须有非空 acceptable")
        if len(set(self.cited_history_steps)) != len(self.cited_history_steps):
            raise ValueError("历史引用步号重复")
        return self


class HistoryReview(BaseModel):
    """完整输入与最终标注一起保存；原始版本限制仍由原始请求来源说明保留。"""

    packet: HistoryPacket
    annotation: Annotation
    history_steps_reviewed: list[int]
    reviewer: Literal["codex_full_history_review"] = "codex_full_history_review"
    evidence_scope: Literal["full_choose_request_and_matching_judge_input"] = (
        "full_choose_request_and_matching_judge_input"
    )


def validate_annotation(packet: HistoryPacket, annotation: Annotation) -> None:
    """引用只能指向该决策以前的本 task 记忆，动作名称与参数名必须来自原空间。"""
    req = packet.request
    if not set(annotation.cited_history_steps).issubset(packet.history_steps):
        raise ValueError(f"{packet.case_id}: 引用了未来或不属于本 task 的历史")
    if packet.history_steps and not annotation.cited_history_steps:
        raise ValueError(f"{packet.case_id}: 有历史却未引用任何历史证据")
    if req.obs.scene not in EVALUATION_SCENES and annotation.status != "outside_scope":
        raise ValueError("不能通过改标签扩张六类范围")
    if "answer_in_memory" in annotation.tags and not packet.history_steps:
        raise ValueError("记忆依赖标签缺少历史证据")
    if "after_failure" in annotation.tags and not req.last_result:
        raise ValueError("after_failure 沿用 spec 的 last_result 失败口径")
    entries = {entry.name: entry for entry in req.space.entries}
    for matcher in annotation.acceptable:
        name = matcher.key or matcher.script
        if not req.space.mask.get(name, False):
            raise ValueError(f"{packet.case_id}: 标签动作越权 {name}")
        if matcher.script:
            entry = entries.get(matcher.script)
            if entry is None or entry.kind != "script":
                raise ValueError("脚本标签缺少原始签名")
            if not set(matcher.args or {}).issubset({param.name for param in entry.params}):
                raise ValueError("脚本标签参数名不在原始签名中")


def make_case(review: HistoryReview, origin: str, version_limit: str) -> ChooseCase:
    """保留完整生产信封与人工委托的助手标注，不冒充 human 来源。"""
    assert review.annotation.status == "eligible"
    annotation, packet = review.annotation, review.packet
    return ChooseCase(
        case_id=packet.case_id,
        request=packet.request,
        acceptable=annotation.acceptable,
        scene=packet.request.obs.scene,
        tags=annotation.tags,
        source="collected",
        label_source="rule",
        origin=origin,
        label_note=f"完整历史重新标注（助手审核，非人工来源）：{annotation.reason}。"
        f"已核对本 task 全部历史步号 {packet.history_steps}；版本限制：{version_limit}",
    )


def apply_annotations(
    packets: list[HistoryPacket],
    annotations: list[Annotation],
    origins: dict[str, tuple[str, str]],
) -> tuple[list[HistoryReview], list[ChooseCase]]:
    """完整覆盖全部现场；只从 eligible 生成评测候选，不冻结或注册。"""
    by_id = {item.case_id: item for item in annotations}
    identifiers = {packet.case_id for packet in packets}
    if len(by_id) != len(annotations) or len(identifiers) != len(packets):
        raise ValueError("重复审核 id")
    if set(by_id) != identifiers or set(origins) != identifiers:
        raise ValueError("审核决定或来源未完整覆盖全部现场")
    records: list[HistoryReview] = []
    cases: list[ChooseCase] = []
    for packet in packets:
        annotation = by_id[packet.case_id]
        validate_annotation(packet, annotation)
        review = HistoryReview(
            packet=packet, annotation=annotation, history_steps_reviewed=packet.history_steps
        )
        records.append(review)
        if annotation.status == "eligible":
            cases.append(make_case(review, *origins[packet.case_id]))
    return records, cases


def summarize(records: list[HistoryReview]) -> dict[str, object]:
    """报告完整历史覆盖、真实 judge 对齐和标注范围，不计算任何模型成绩。"""
    return {
        "review_scope": "full_choose_request_and_matching_judge_input",
        "reviewed": len(records),
        "history_entries": sum(len(row.packet.request.memories) for row in records),
        "judge_inputs_exactly_matched": sum(row.packet.judge_input_verified for row in records),
        "task_entry_without_history": sum(not row.packet.history_steps for row in records),
        "statuses": dict(Counter(row.annotation.status for row in records)),
        "eligible_scenes": dict(
            Counter(
                row.packet.request.obs.scene
                for row in records
                if row.annotation.status == "eligible"
            )
        ),
        "cases_with_script_matchers": sum(
            any(matcher.script for matcher in row.annotation.acceptable)
            for row in records
            if row.annotation.status == "eligible"
        ),
        "frozen": False,
        "notes": [
            "助手受托审核，label_source 保持 rule，不冒称人工审核",
            "脚本按现有契约核名称与目标参数，不运行脚本、不模拟其未来结果",
            "原批次采集版本限制保留；start_menu 未覆盖；不引入其他 task 的记忆",
            "只使用 choose 之前的 judge 输入，不读取 judge 答案或之后执行结果",
        ],
    }
