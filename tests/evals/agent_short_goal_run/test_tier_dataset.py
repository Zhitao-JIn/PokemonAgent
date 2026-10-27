"""样本档位与冻结内容的契约（D8）：三档各自的必需项，加载期就报 `DatasetError`。

**为什么这个文件值钱**：档位决定哪一层规划被冻结，档位与内容对不上时（mid 却带了 task 表、
short 却没有 task 表、long 却带目标表）在运行期只会表现成"开关开了却没东西可派"的断言，
或者更糟——悄悄退回自由规划。这里把这条契约钉在加载口上：数据错就进不了批跑。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.agent_short_goal_run.dataset import loader
from evals.agent_short_goal_run.dataset.schemas import (
    EvalSample,
    SampleGoal,
    SampleStart,
    SampleTask,
)
from evals.dataset.errors import DatasetError


def _task(goal: str = "走到草丛") -> SampleTask:
    return SampleTask(goal=goal, success_criteria=f"{goal}完成", max_steps=2)


def _goal(goal: str = "进草地", *, tasks: list[SampleTask] | None = None) -> SampleGoal:
    return SampleGoal(
        goal=goal, success_criteria=f"{goal}完成", max_steps=3, tasks=list(tasks or [])
    )


def _sample(*, tier: str = "long", goals: list[SampleGoal] | None = None) -> EvalSample:
    return EvalSample(
        sample_id="s1",
        dataset_version="v1",
        category="c",
        start=SampleStart(kind="state", source_state="x.state", source_sha256="0" * 64),
        goal="总目标",
        success_criteria="总判据",
        max_steps=3,
        behavior="b",
        check_id=None,
        rubric=[],
        red_lines=[],
        k_metric="pass_at_k",
        split="test",
        tier=tier,  # type: ignore[arg-type]
        goals=list(goals or []),
    )


def test_the_three_tiers_accept_their_own_shape() -> None:
    """long 无目标表、mid 有目标表无 task、short 单条目标带 task —— 三档各一条合法样本。"""
    loader.validate_tiers(
        [
            _sample(tier="long"),
            _sample(tier="mid", goals=[_goal("进草地"), _goal("出草地")]),
            _sample(tier="short", goals=[_goal("进草地", tasks=[_task()])]),
        ]
    )


@pytest.mark.parametrize(
    ("tier", "goals", "message"),
    [
        ("mid", [_goal("进草地", tasks=[_task()])], "mid 档第 1 条目标不该带 tasks"),
        ("short", [_goal("进草地")], "short 档第 1 条目标需要非空 tasks"),
        ("long", [_goal("进草地")], "long 档不该带 goals"),
        ("mid", [], "mid 档需要非空 goals"),
        ("short", [_goal("进草地", tasks=[_task()]), _goal("出草地", tasks=[_task()])], "恰一条"),
    ],
)
def test_a_tier_that_contradicts_its_content_is_rejected(
    tier: str, goals: list[SampleGoal], message: str
) -> None:
    """非法组合：报 `DatasetError`，消息指出是哪一档哪里不对。"""
    with pytest.raises(DatasetError, match=message):
        loader.validate_tiers([_sample(tier=tier, goals=goals)])


def test_every_problem_is_reported_in_one_go(tmp_path: Path) -> None:
    """多条样本一起出错时全部列出，不只第一条。"""
    samples = [
        _sample(tier="long", goals=[_goal("进草地")]),
        _sample(tier="mid", goals=[_goal("进草地", tasks=[_task()])]),
    ]

    with pytest.raises(DatasetError) as caught:
        loader.validate_tiers(samples)

    assert "long 档不该带 goals" in str(caught.value)
    assert "mid 档第 1 条目标不该带 tasks" in str(caught.value)


def _write_version(root: Path, sample: dict) -> None:
    """在临时根下写一个最小版本目录（样本 + 空 rubric + 起点文件）。"""
    version = root / "v1"
    version.mkdir(parents=True)
    (version / "start.state").write_bytes(b"state")
    (version / "samples.jsonl").write_text(
        json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (version / "rubric.json").write_text(
        json.dumps({"version": "v1", "items": [], "red_lines": []}), encoding="utf-8"
    )


def test_loading_a_version_reports_the_tier_violation(tmp_path: Path, monkeypatch) -> None:
    """`load()` 走的是 `check()`：档位不合规在**加载期**就抛 `DatasetError`。"""
    sample = _sample(tier="long", goals=[_goal("进草地")]).model_dump(mode="json")
    sample["start"]["source_sha256"] = hashlib.sha256(b"state").hexdigest()
    _write_version(tmp_path, sample)
    monkeypatch.setattr(loader, "DATASET_DIR", tmp_path)

    with pytest.raises(DatasetError, match="long 档不该带 goals"):
        loader.load("v1")
