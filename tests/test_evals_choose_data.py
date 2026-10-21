"""规则草稿用法：证据不足保留待审，绝不以采集时模型输出作为标签。"""

import json
from pathlib import Path

import pytest

from evals.dataset.brain_choose.build.from_capture import (
    CaptureRow,
    build_drafts,
    capture_version_note,
    read_request,
    write_rows,
)
from evals.dataset.brain_choose.build.prelabel import candidate_keys, walking_keys
from evals.dataset.brain_choose.build.ram_review import Decision, apply_review
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.world.interface.domain.ram_readout import RamReadout


def request(
    overlay: str = "none", goal: str = "移动", criteria: str = "到达"
) -> FromHarnessToBrainToolChooseOnceReq:
    """最小生产信封，不引入模拟器或模型。"""
    return FromHarnessToBrainToolChooseOnceReq.model_validate(
        {
            "goals": [{"goal": goal, "criteria": criteria}],
            "obs": {
                "step": 0,
                "status": "测试现场",
                "scene": "walk",
                "facts": {"overlay": overlay},
            },
            "space": {
                "scene": "walk",
                "names": ["a", "up", "right"],
                "mask": {"a": True, "up": True, "right": True},
            },
            "memories": [],
        }
    )


def test_shortest_visible_route_keeps_both_first_steps() -> None:
    grid = "y=0  ...  (x=0..2)\ny=1  .@.  (x=0..2)"

    keys = walking_keys(grid, (1, 1), "where x=2 y=0")

    assert set(keys) == {"up", "right"}


@pytest.mark.parametrize("target", ["x=3 y=0", "x=2 y=0 或 x=0 y=0", "x=2 y>=0"])
def test_uncertain_or_offscreen_coordinate_is_pending(target: str) -> None:
    assert walking_keys("y=0  @..  (x=0..2)", (0, 0), target) == []


@pytest.mark.parametrize("obstacle", ["#", "D", "N", "v", "<", ">"])
def test_walls_transitions_and_ledges_are_not_guessed(obstacle: str) -> None:
    assert walking_keys(f"y=0  @{obstacle}.  (x=0..2)", (0, 0), "x=2 y=0") == []


def test_dialog_candidate_respects_original_mask() -> None:
    req = request("dialog")
    req.obs.facts.dialog_text = "Welcome!"

    assert candidate_keys(req)[0] == ["a"]
    req.space.mask["a"] = False
    assert candidate_keys(req)[0] == []


def test_menu_confirmation_requires_unique_explicit_target() -> None:
    req = request("choice", "确认 BUY")
    req.obs.facts.options = ["BUY", "SELL", "QUIT"]
    req.obs.facts.cursor = "BUY"

    assert candidate_keys(req)[0] == ["a"]
    req.goals[-1].goal = "从 BUY 移到 QUIT 并确认"
    assert candidate_keys(req)[0] == []
    req.goals[-1].goal = "不要确认 BUY"
    assert candidate_keys(req)[0] == []


def capture(tmp_path: Path) -> CaptureRow:
    """构造真实结构的同帧旁证，响应字段故意指向不存在文件。"""
    req = request("dialog")
    req.obs.facts.dialog_text = "Welcome!"
    ram = RamReadout.model_validate(
        {
            "in_battle": False,
            "covered": True,
            "text_source": "decode",
            "menu": {"current_item": 0, "max_item": 0, "top_x": 0},
            "money": 0,
            "bag": [],
            "party": [],
            "decoded": {"dialog_text": "Welcome!", "options": [], "cursor": ""},
        }
    )
    (tmp_path / "request.json").write_text(req.model_dump_json(), encoding="utf-8")
    context = {
        "sense_event": {
            "content": {
                "status": req.obs.status,
                "facts": req.obs.facts.model_dump(mode="json"),
                "frame": "test-frame",
                "ram": ram.model_dump(mode="json"),
            }
        },
        "effective_action_event": "poisoned: press b",
        "execution_event": None,
    }
    (tmp_path / "context.json").write_text(json.dumps(context), encoding="utf-8")
    row = CaptureRow(
        id="sample/1",
        sample_id="sample",
        scene="walk",
        task_goal="移动",
        task_criteria="到达",
        request="request.json",
        context="context.json",
    )
    index = [{**row.model_dump(), "response": "does-not-exist.json"}]
    (tmp_path / "capture_index.json").write_text(json.dumps(index), encoding="utf-8")
    return row


def test_prelabel_does_not_read_responses_or_execution(tmp_path: Path) -> None:
    capture(tmp_path)

    cases, reviews = build_drafts(tmp_path)

    assert cases[0].acceptable[0].key == "a"
    assert "未审" in cases[0].label_note
    assert "无法证明" in cases[0].label_note
    assert reviews[0].status == "rule_draft"


def test_mismatched_ram_evidence_fails_before_labelling(tmp_path: Path) -> None:
    row = capture(tmp_path)
    context_path = tmp_path / row.context
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["sense_event"]["content"]["ram"]["decoded"]["dialog_text"] = "other frame"
    context_path.write_text(json.dumps(context), encoding="utf-8")

    with pytest.raises(ValueError, match="RAM"):
        read_request(tmp_path, row)


def test_writer_refuses_existing_files(tmp_path: Path) -> None:
    path = tmp_path / "draft.jsonl"
    write_rows(path, [])

    with pytest.raises(FileExistsError):
        write_rows(path, [])


def test_supplement_ids_do_not_collide_with_original_capture(tmp_path: Path) -> None:
    capture(tmp_path)

    cases, reviews = build_drafts(tmp_path, case_prefix="supplement")

    assert cases[0].case_id == "supplement/sample/1"
    assert reviews[0].batch == str(tmp_path)


def test_changed_production_digest_blocks_supplement(tmp_path: Path) -> None:
    first = {"head": "same", "production_sha256": "before"}
    last = {"head": "same", "production_sha256": "after"}
    (tmp_path / "code_before.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "code_after.json").write_text(json.dumps(last), encoding="utf-8")

    with pytest.raises(ValueError, match="不一致"):
        capture_version_note(tmp_path)


@pytest.mark.parametrize("verdict,keys", [("local_supported", []), ("goal_conflict", ["a"])])
def test_ram_review_does_not_turn_uncertainty_into_a_label(verdict: str, keys: list[str]) -> None:
    with pytest.raises(ValueError, match="local_supported"):
        Decision(case_id="one", verdict=verdict, keys=keys, reason="test")


def test_ram_review_requires_exact_source_coverage(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="完整覆盖"):
        apply_review(source, [Decision(case_id="absent", verdict="outside_scope", reason="test")])
