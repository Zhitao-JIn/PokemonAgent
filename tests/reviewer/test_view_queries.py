"""查询 schema 是终端与 AI 共用的注册表，非法坐标和 hint 必须在边界拒绝。"""

import pytest
from pydantic import TypeAdapter, ValidationError

from pokemon_agent.schemas.reviewer import (
    BrainFramesQuery,
    FrameQuery,
    RecallQuery,
    TraceQuery,
    ViewAnswer,
    ViewQuery,
)


@pytest.mark.parametrize(
    "data, expected",
    [
        ({"tool": "read_trace", "run_id": "old-run"}, TraceQuery),
        ({"tool": "recall", "conditions": {"run_goal": "badge"}}, RecallQuery),
        ({"tool": "recall", "conditions": {"runs": "all"}}, RecallQuery),
        ({"tool": "read_frame", "which": "latest"}, FrameQuery),
        ({"tool": "read_frame", "episode_id": "e1", "step": 0}, FrameQuery),
        ({"tool": "read_brain_frames", "offset": 20, "limit": 2}, BrainFramesQuery),
    ],
)
def test_one_discriminated_schema_covers_all_query_tools(data: dict, expected: type) -> None:
    query = TypeAdapter(ViewQuery).validate_python(data)

    assert isinstance(query, expected)
    assert TypeAdapter(ViewQuery).validate_json(query.model_dump_json()) == query


@pytest.mark.parametrize(
    "data",
    [
        {"tool": "unknown"},
        {"tool": "recall", "conditions": {"kind": "act"}},
        {"tool": "recall", "conditions": {"runs": "some"}},
        {"tool": "recall", "conditions": {"runs": "all", "run_id": "r1"}},
        {"tool": "recall", "limit": 9},
        {"tool": "recall", "limit": 0},
        {"tool": "read_trace", "last_n": 51},
        {"tool": "read_trace", "offset": -1},
        {"tool": "read_trace", "content_limit": 2001},
        {"tool": "read_trace", "kind": "unknown"},
        {"tool": "read_trace", "unexpected": 1},
        {"tool": "read_frame", "which": "latest", "step": 1},
        {"tool": "read_frame", "which": "latest", "episode_id": "e1"},
        {"tool": "read_frame", "which": "before", "step": 1},
        {"tool": "read_frame", "episode_id": "e1"},
        {"tool": "read_frame", "episode_id": "e1", "step": -1},
        {"tool": "read_brain_frames", "limit": 3},
    ],
)
def test_query_boundaries_reject_invalid_inputs(data: dict) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ViewQuery).validate_python(data)


def test_frame_answers_have_the_same_image_count_bound_as_queries() -> None:
    with pytest.raises(ValidationError):
        ViewAnswer(ok=True, text="frames", images=["a", "b", "c"])
