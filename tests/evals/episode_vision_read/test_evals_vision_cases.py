"""视觉调用失败的分母约定与解析失败的计分用法。"""

from _doubles.vision import DownVision

from evals.episode_vision_read.compare import field_verdict, truth_fields
from evals.episode_vision_read.dataset import build_cases, output_for, select_frames
from evals.episode_vision_read.solver import SCORE_KEYS, PerceiveRun


def test_unreachable_frames_have_no_test_case_and_are_reported_with_their_id():
    frame = select_frames(per_scene=1)[0]

    cases, failures = build_cases([frame], DownVision(), workers=2)

    assert cases == []
    assert len(failures) == 1 and failures[0].sample_id == frame.sample_id
    assert "gateway down" in failures[0].reason


def test_parse_failure_fails_only_fields_with_an_independent_expected_value():
    frame = select_frames(per_scene=1)[0]
    run = PerceiveRun(failure="不能解析", raw="bad JSON")
    truth = truth_fields(frame)

    verdicts = {key: field_verdict(output_for(run), truth, key).value for key in SCORE_KEYS}

    assert verdicts["parsed"] == "I"
    assert all(value == ("I" if key in truth else "N") for key, value in verdicts.items())
