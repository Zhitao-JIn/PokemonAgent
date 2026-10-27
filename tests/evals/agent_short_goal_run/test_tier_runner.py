"""`one.py` 按档位组装（D9/D10）：`harness.run` 的入参与样本级配置覆盖逐项对得上。

**为什么这个文件值钱**：档位到 harness 入参的翻译只有这一处，写错了不会报错——只会表现成
"中期样本的目标表没生效"或"短期样本的 task 表没进 episode"。这里用替身 harness 逐项断言：

- `long`：空目标表 + 不传 `frozen_tasks` + 不覆盖 `loop`（与改动前完全一致）；
- `mid`：目标表按 `<sample_id>-g<n>` 编号，打开 `freeze_run_plan`；
- `short`：单条目标 + `frozen_tasks` 按 `<sample_id>-g1` 挂着 `<sample_id>-g1-t<m>`，两个开关都开。

不启动模拟器、不调用真实模型：`build_real` 换成替身，世界端只记下起点路径。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import evals.agent_short_goal_run.solver.runner.one as one
from evals.agent_short_goal_run.dataset.schemas import (
    EvalSample,
    SampleGoal,
    SampleStart,
    SampleTask,
)
from evals.paths import REPO_ROOT
from pokemon_agent.brain import Goal, Task


class _Harness:
    """替身 harness：记下每次 `run` 的全部入参。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, run_id, goals, run_goal=None, **kwargs):
        self.calls.append({"run_id": run_id, "goals": goals, "run_goal": run_goal, **kwargs})
        return _Result()


class _Result:
    """`run_result.json` 只要求能序列化；分支名要给 `run.json`。"""

    branch = "main"

    def model_dump_json(self, indent: int = 2) -> str:
        return "{}"


class _Game:
    """世界端替身：只记起点路径与释放。"""

    def __init__(self) -> None:
        self.start_state: Path | None = None

    def use_start_state(self, path: Path) -> None:
        self.start_state = path

    def release_lease(self) -> None:
        return None


def _task(goal: str, max_steps: int = 2) -> SampleTask:
    return SampleTask(goal=goal, success_criteria=f"{goal}完成", max_steps=max_steps)


def _goal(goal: str, *, tasks: list[SampleTask] | None = None) -> SampleGoal:
    return SampleGoal(
        goal=goal, success_criteria=f"{goal}完成", max_steps=3, tasks=list(tasks or [])
    )


def _sample(*, tier: str = "long", goals: list[SampleGoal] | None = None) -> EvalSample:
    return EvalSample(
        sample_id="demo",
        dataset_version="v1",
        category="c",
        start=SampleStart(kind="state", source_state="x.state", source_sha256="0" * 64),
        goal="总目标",
        success_criteria="总判据",
        max_steps=7,
        behavior="b",
        check_id=None,
        rubric=[],
        red_lines=[],
        k_metric="pass_at_k",
        split="test",
        tier=tier,  # type: ignore[arg-type]
        goals=list(goals or []),
    )


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample: EvalSample
) -> tuple[dict, dict, _Game]:
    """跑一条样本（替身装配），返回 `harness.run` 的入参、落盘的样本配置、世界桩。"""
    harness, game = _Harness(), _Game()
    monkeypatch.setattr(one, "build_real", lambda config: (harness, game))
    monkeypatch.chdir(REPO_ROOT)
    work = tmp_path / "work"

    one.run_one(sample, work, run_config_path="run-config.json")

    overlay = json.loads((work / "config-main.json").read_text(encoding="utf-8"))
    assert json.loads((work / "run.json").read_text(encoding="utf-8"))["error"] == ""
    return harness.calls[-1], overlay, game


def test_the_long_tier_keeps_the_old_call_shape(tmp_path, monkeypatch) -> None:
    """long：空目标表、不传 frozen_tasks、不覆盖 loop；run goal 与引导 Task 照旧。"""
    sample = _sample()

    call, overlay, game = _run(tmp_path, monkeypatch, sample)

    assert call["run_id"] == "eval-demo"
    assert call["goals"] == [], "目标表仍由 planner 建"
    assert call["frozen_tasks"] is None
    assert call["run_goal"] == Goal(goal=sample.goal, criteria=sample.success_criteria)
    assert call["sample_id"] == "demo"
    assert call["start_task"].task_id == "demo" and call["start_task"].max_steps == 7
    assert "loop" not in overlay, "long 档不动配置开关"
    assert overlay["run"] == {"run_id": "eval-demo", "branch": "main"}
    assert game.start_state is not None


def test_the_mid_tier_freezes_the_goal_table(tmp_path, monkeypatch) -> None:
    """mid：目标表按样本 id 编号，只打开 run 层冻结。"""
    sample = _sample(tier="mid", goals=[_goal("进草地"), _goal("出草地")])

    call, overlay, _ = _run(tmp_path, monkeypatch, sample)

    assert [(goal.task_id, goal.goal) for goal in call["goals"]] == [
        ("demo-g1", "进草地"),
        ("demo-g2", "出草地"),
    ]
    assert [goal.max_steps for goal in call["goals"]] == [3, 3]
    assert call["frozen_tasks"] is None, "mid 不冻结 task 表"
    assert overlay["loop"] == {"freeze_run_plan": True}


def test_the_short_tier_freezes_both_layers(tmp_path, monkeypatch) -> None:
    """short：单条目标 + 它的 task 表（编号 `<sample_id>-g1-t<m>`），两个开关都开。"""
    sample = _sample(
        tier="short",
        goals=[_goal("进草地", tasks=[_task("走到草丛"), _task("蹲进草里")])],
    )

    call, overlay, _ = _run(tmp_path, monkeypatch, sample)

    assert [goal.task_id for goal in call["goals"]] == ["demo-g1"]
    assert call["frozen_tasks"] == {
        "demo-g1": [
            Task(
                task_id="demo-g1-t1",
                goal="走到草丛",
                success_criteria="走到草丛完成",
                max_steps=2,
            ),
            Task(
                task_id="demo-g1-t2",
                goal="蹲进草里",
                success_criteria="蹲进草里完成",
                max_steps=2,
            ),
        ]
    }
    assert overlay["loop"] == {"freeze_run_plan": True, "freeze_episode_plan": True}
    assert call["run_goal"] == Goal(goal=sample.goal, criteria=sample.success_criteria)
