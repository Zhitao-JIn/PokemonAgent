"""完整历史标注用法：对齐真实 judge 输入，禁止未来/跨 task 信息，保留完整生产请求。"""

import json
from pathlib import Path

import pytest

from evals.brain_choose.compare import matches
from evals.dataset.brain_choose.build.from_capture import CaptureRow
from evals.dataset.brain_choose.build.history_context import (
    HistoryPacket,
    JudgeInput,
    build_packet,
    load_packets,
    validate_history,
)
from evals.dataset.brain_choose.build.history_review import (
    Annotation,
    HistoryReview,
    validate_annotation,
)
from evals.dataset.brain_choose.schemas import ChooseCase
from pokemon_agent.brain.interface import Action

ROOT = Path(__file__).resolve().parents[1] / "evals/dataset/brain_choose"


@pytest.fixture(scope="module")
def packets() -> list[HistoryPacket]:
    """从录制真源重建；不调用模型/模拟器，不读取选择结果作为标签。"""
    return load_packets(ROOT / "build/goals.jsonl")


def test_every_record_uses_complete_same_task_history_and_real_judge_input(
    packets: list[HistoryPacket],
) -> None:
    assert len(packets) == 258
    assert sum(len(packet.request.memories) for packet in packets) == 810
    assert sum(packet.judge_input_verified for packet in packets) == 190
    assert sum(not packet.history_steps for packet in packets) == 68
    assert all(packet.matched_judge_event_ids for packet in packets if packet.history_steps)
    assert all(
        memory.before_frame and memory.after_frame
        for packet in packets
        for memory in packet.request.memories
    )


@pytest.mark.parametrize("mutation", ["future", "other_task", "missing_frame"])
def test_history_cannot_be_replaced_with_future_or_unavailable_evidence(
    packets: list[HistoryPacket], mutation: str
) -> None:
    packet = next(item for item in packets if item.history_steps)
    req = packet.request.model_copy(deep=True)
    meta = {key: getattr(packet, key) for key in ("run_id", "episode_id", "task_id")}
    if mutation == "future":
        req.memories[-1].step = req.obs.step
    elif mutation == "other_task":
        req.memories[-1].task_id = "another-task"
    else:
        req.memories[-1].before_frame = None

    with pytest.raises(ValueError):
        validate_history(req, meta)


def test_relabelling_uses_past_menu_transition_instead_of_wrong_direction_hint() -> None:
    reviews = [
        HistoryReview.model_validate_json(line)
        for line in (ROOT / "build/history_review.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    record = next(
        row for row in reviews if row.packet.case_id == "knowledge_battle_action_menu/000002"
    )

    assert record.packet.history_steps == [0]
    assert record.packet.request.memories[0].action == "right"
    assert record.packet.request.memories[0].after.facts.cursor == "PKMN"
    assert record.annotation.status == "eligible"
    assert [matcher.key for matcher in record.annotation.acceptable] == ["down"]
    assert record.annotation.cited_history_steps == [0]


def test_acceptable_actions_include_scripts_and_preserve_original_full_requests(
    packets: list[HistoryPacket],
) -> None:
    cases = [
        ChooseCase.model_validate_json(line)
        for line in (ROOT / "v1/cases_draft.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    inputs = {packet.case_id: packet.request for packet in packets}

    assert len(cases) == 189
    assert sum(any(matcher.script for matcher in case.acceptable) for case in cases) == 105
    assert all(case.request == inputs[case.case_id] for case in cases)
    opening = next(case for case in cases if case.case_id == "knowledge_npc_dialogue/000003")
    closing = next(
        case for case in cases if case.case_id.endswith("/knowledge_npc_dialogue/000002")
    )
    assert not any(matcher.script == "talk_to_adjacent_npc" for matcher in opening.acceptable)
    assert any(matcher.script == "talk_to_adjacent_npc" for matcher in closing.acceptable)
    purchase = next(
        case for case in cases if case.case_id == "knowledge_shop_confirm_purchase/000004"
    )
    assert matches(
        Action(script={"name": "buy_item", "args": {"item": "POKé BALL", "count": 1}}),
        purchase.acceptable,
    )
    assert not matches(
        Action(script={"name": "buy_item", "args": {"item": "POKé BALL", "count": 2}}),
        purchase.acceptable,
    )
    assert (ROOT / "v1/cases.jsonl").read_bytes() == (ROOT / "v1/cases_draft.jsonl").read_bytes()


def test_single_frame_review_is_superseded_and_all_records_have_new_disposition() -> None:
    old = json.loads((ROOT / "build/ram_review_report.json").read_text(encoding="utf-8"))
    new = json.loads((ROOT / "build/history_review_report.json").read_text(encoding="utf-8"))

    assert old["superseded"] is True and old["valid_for_annotation"] is False
    assert new["statuses"] == {"eligible": 189, "excluded": 67, "outside_scope": 2}
    assert new["judge_inputs_exactly_matched"] == 190


def test_annotations_cannot_cite_a_later_step(packets: list[HistoryPacket]) -> None:
    packet = next(item for item in packets if item.history_steps)
    annotation = Annotation(
        case_id=packet.case_id,
        status="excluded",
        reason="test",
        cited_history_steps=[packet.request.obs.step],
    )

    with pytest.raises(ValueError, match="未来"):
        validate_annotation(packet, annotation)


def test_packet_needs_no_response_file_and_rejects_a_future_judge_call(
    packets: list[HistoryPacket], tmp_path: Path
) -> None:
    original = packets[0]
    req = original.request
    (tmp_path / "request.json").write_text(req.model_dump_json(), encoding="utf-8")
    meta = {key: getattr(original, key) for key in ("run_id", "episode_id", "task_id")}
    meta["step"] = 1
    context = {
        "meta": meta,
        "choose_call_events": [{"seq": 10}],
        "sense_event": {
            "content": {
                "facts": req.obs.facts.model_dump(mode="json"),
                "status": req.obs.status,
                "ram": original.current_ram.model_dump(mode="json"),
                "frame": original.current_frame,
            }
        },
        "execution_event": "poisoned",
    }
    (tmp_path / "context.json").write_text(json.dumps(context), encoding="utf-8")
    row = CaptureRow(
        id="one",
        sample_id="one",
        scene="walk",
        task_goal=req.goals[-1].goal,
        task_criteria=req.goals[-1].criteria,
        request="request.json",
        context="context.json",
    )

    packet = build_packet(tmp_path, row, {})

    assert packet.request == req
    marker = (original.episode_id, original.task_id, 1)
    future = JudgeInput(event_id="future", sequence=11, prompt=packet.judge_prompt, images=[])
    with pytest.raises(ValueError, match="之后"):
        build_packet(tmp_path, row, {marker: [future]})
