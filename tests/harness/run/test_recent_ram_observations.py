"""run 判定仅收到同 run、同分支最近五条真实 RAM 观测。"""

import json

from pokemon_agent.harness.run.review_and_judge.recent_ram_observations import (
    recent_ram_observations,
)
from pokemon_agent.schemas.harness import TraceEvent


def _event(index: int, *, run_id: str = "r", branch: str = "main", ram: bool = True) -> TraceEvent:
    """一份真实形状的账本读数，HP 随观测编号变化。"""
    payload = {
        "in_battle": False,
        "covered": True,
        "text_source": "decode",
        "menu": {"current_item": 0, "max_item": 0, "top_x": 0},
        "money": 100,
        "bag": [],
        "party": [{"species": 1, "level": 7, "hp": index, "max_hp": 25, "status": "ok"}],
        "decoded": {"dialog_text": "", "options": [], "cursor": ""},
    }
    return TraceEvent(
        uuid=f"event-{run_id}-{branch}-{index}",
        seq=index,
        kind="sense_frame",
        type="view",
        started_at=float(index),
        ended_at=float(index),
        meta=json.dumps(
            {
                "run_id": run_id,
                "branch": branch,
                "source": "task.sense",
                "episode_id": "ep",
                "task_id": "task",
                "step": index,
            }
        ),
        content=json.dumps({"ram": payload if ram else None}),
    )


def test_recent_five_preserve_chronological_order_and_numeric_evidence() -> None:
    events = [_event(i) for i in reversed(range(8))]

    records = recent_ram_observations(events, run_id="r", branch="main")

    assert [record.step for record in records] == [3, 4, 5, 6, 7]
    assert [record.ram.party[0].hp for record in records] == [3, 4, 5, 6, 7]
    assert records[-1].event_id == "event-r-main-7"


def test_other_runs_branches_and_missing_ram_do_not_displace_valid_frames() -> None:
    events = [
        _event(1),
        _event(2),
        _event(20, run_id="other"),
        _event(30, branch="other"),
        _event(40, ram=False),
    ]

    records = recent_ram_observations(events, run_id="r", branch="main")

    assert [record.step for record in records] == [1, 2]


def test_empty_history_does_not_invent_observations() -> None:
    assert recent_ram_observations([], run_id="r", branch="main") == []


def test_same_timestamp_is_ordered_by_trace_sequence() -> None:
    first = _event(1).model_copy(update={"ended_at": 10.0})
    second = _event(2).model_copy(update={"ended_at": 10.0})

    records = recent_ram_observations([second, first], run_id="r", branch="main")

    assert [record.sequence for record in records] == [1, 2]
