"""公开评测任务与冻结解码、分母和记忆排序指标的使用示范。"""

import ast
from pathlib import Path

import pytest
from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState

from evals.agent_short_goal_run.scorer.judged import judged_accuracy, judged_count
from evals.brain_judge.scorer import confusion
from evals.dataset.brain_judge import JudgeCaseV1
from evals.dataset.brain_judge.loader import DATASET_DIR
from evals.dataset.frames import load as load_frames
from evals.decode.compare import field_verdict, truth_for
from evals.decode.solver import decode_frame
from evals.memory_store_recall.compare import retrieval_metrics
from evals.registry import TASKS
from evals.world_script_execute.dataset import load as load_scripts

DATASET = DATASET_DIR / "v1" / "dataset.jsonl"


@scorer(metrics=[judged_accuracy(), judged_count()])
def labelled_group() -> Scorer:
    """合成原始标记验证 inspect 汇总，不经过实际模型。"""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=state.metadata["mark"])

    return score


def test_inspect_aggregation_excludes_unlabelled_groups(tmp_path: Path) -> None:
    task = Task(
        dataset=[Sample(id=mark, input=mark, metadata={"mark": mark}) for mark in ("C", "I", "N")],
        solver=[],
        scorer=labelled_group(),
        model="none",
    )

    log = eval(task, log_dir=str(tmp_path), display="none")[0]

    assert log.status == "success"
    assert log.results is not None
    metrics = log.results.scores[0].metrics
    assert metrics["judged_accuracy"].value == 0.5
    assert metrics["judged_count"].value == 2


@pytest.mark.parametrize(
    ("actual", "truth", "key", "value"),
    [
        ({}, None, "options", "N"),
        ({}, {}, "options", "N"),
        ({}, {"cursor": ""}, "options", "N"),
        ({"options": []}, {"options": []}, "options", "C"),
        ({"options": ["wrong"]}, {"options": []}, "options", "I"),
        ({}, {"cursor_cell": None}, "cursor_cell", "I"),
        ({"cursor_cell": None}, {"cursor_cell": None}, "cursor_cell", "C"),
        ({"cursor": ""}, {"cursor": ""}, "cursor", "C"),
        ({"in_battle": False}, {"in_battle": False}, "in_battle", "C"),
        ({"view": {"money": 0}}, {"view.money": 0}, "view.money", "C"),
        (
            {"screen": "hello world"},
            {"screen_contains": ["hello", "world"]},
            "screen_contains",
            "C",
        ),
        ({"screen": "hello"}, {"screen_contains": ["world"]}, "screen_contains", "I"),
    ],
)
def test_decode_fields_skip_only_missing_truth_and_score_empty_truth(actual, truth, key, value):
    assert field_verdict(actual, truth, key).value == value


def test_only_the_eight_evaluation_tasks_are_public() -> None:
    assert set(TASKS) == {
        "brain_plan",
        "brain_decompose",
        "brain_choose",
        "decode",
        "memory_store_recall",
        "world_script_execute",
        "brain_judge",
        "agent_short_goal_run",
    }
    assert sum(entry.kind == "deepeval" for entry in TASKS.values()) == 3
    assert sum(entry.kind == "inspect" for entry in TASKS.values()) == 5
    for name, entry in TASKS.items():
        if entry.kind == "deepeval":
            assert Path(entry.entry.replace(".", "/"), "__main__.py").is_file()
        else:
            tree = ast.parse(Path(entry.entry).read_text(encoding="utf-8"))
            assert any(
                isinstance(node, ast.FunctionDef)
                and node.name == name
                and any(
                    isinstance(dec, ast.Name) and dec.id == "task" for dec in node.decorator_list
                )
                for node in tree.body
            )


def test_world_script_execute_contains_all_script_samples() -> None:
    cases = load_scripts()

    assert len(cases) == 106
    assert len({case.case_id for case in cases}) == 106


def test_unlabelled_groups_do_not_turn_into_successes() -> None:
    assert field_verdict({"map_id": 12}, None, "map_id").value == "N"
    assert field_verdict({"map_id": 12}, {}, "map_id").value == "N"
    assert field_verdict({"map_id": 12}, {"map_id": 13}, "map_id").value == "I"


def test_decode_loads_all_independent_truth_without_falling_back_to_prelabels() -> None:
    frame = next(frame for frame in load_frames() if frame.source == "probe_0926")

    screen_truth = truth_for(frame, "screen")

    assert screen_truth is not None and screen_truth["overlay"] == frame.label.overlay
    assert truth_for(frame, "scene") is not None
    assert truth_for(frame, "takeover") is not None


def test_frozen_shop_frame_decodes_without_a_live_emulator() -> None:
    frame = next(frame for frame in load_frames() if frame.sample_id == "takeover:shop_items")

    run = decode_frame(frame)

    assert run.scene["scene"] == "shop_items"
    assert run.takeover["view"]["money"] == 3000
    assert field_verdict(run.takeover, frame.takeover_truth, "view").value == "C"


@pytest.mark.parametrize("case_id", ["route1_ledge", "route1_grass"])
def test_documented_terrain_frames_load_all_labelled_groups(case_id: str) -> None:
    frame = next(frame for frame in load_frames() if frame.sample_id == f"terrain:{case_id}")

    run = decode_frame(frame)

    assert frame.screen_truth is not None and frame.takeover_truth is not None
    assert frame.terrain_truth is not None and "walk_map" in frame.terrain_truth
    assert "存档速记" in frame.note
    assert all(
        field_verdict(run.terrain, frame.terrain_truth, key).value == "C"
        for key in frame.terrain_truth
    )


def test_recall_uses_all_relevant_records_and_mrr_uses_the_first_hit() -> None:
    assert retrieval_metrics(["irrelevant", "second", "first"], ["first", "second"], 2) == (
        0.5,
        0.5,
    )
    assert retrieval_metrics(["irrelevant"], ["first"], 5) == (0.0, 0.0)


def test_judge_labels_are_independent_and_all_four_cells_are_counted() -> None:
    cases = [
        JudgeCaseV1.model_validate_json(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
    ]

    assert {case.achieved for case in cases} == {True, False}
    assert confusion(True, False) == {"TP": 0, "FP": 1, "FN": 0, "TN": 0}
    assert confusion(False, True) == {"TP": 0, "FP": 0, "FN": 1, "TN": 0}
