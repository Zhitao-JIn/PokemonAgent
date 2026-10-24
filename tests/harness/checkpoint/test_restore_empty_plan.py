"""恢复路径的空 plan 口径：`goals` 表为空时，reset 用按 run goal 合成的引导 `Task`（634）。

只走 `open_branch`（读清单 → 装配新线 → 回档世界与记忆 → 记首条账），不进图：
`restore_run` 的整图那段是硬跳过的慢测试（`test_checkpoint_restore.py`），
而"空表能不能 reset"这件事在回档这一段就决定了。
"""

from __future__ import annotations

import pathlib
from typing import Any

from _fake_run import build_fake

from pokemon_agent.brain import Goal
from pokemon_agent.harness.checkpoint import open_branch
from pokemon_agent.harness.run.run_entry import start_task_for
from pokemon_agent.harness.run.run_state import RunState


class _RecordingGame:
    """包住假世界，只记 `reset` 收到的 `Task`（其余口原样转发）。"""

    def __init__(self, inner: Any) -> None:
        self._inner, self.tasks = inner, []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def reset(self, req) -> None:
        self.tasks.append(req.task)
        self._inner.reset(req)


def test_open_branch_resets_with_a_synthetic_task_when_the_plan_is_empty(
    tmp_path: pathlib.Path,
) -> None:
    """空目标表的存档恢复：不 IndexError，reset 收到 `start_task_for` 合成的 Task。"""
    goal = Goal(goal="和两位不同的 NPC 各说一次话", criteria="两位 NPC 都开过口")
    seed = build_fake(tmp_path, checkpoints=True)
    assert seed.checkpointer is not None
    seed.checkpointer.save(
        "run",
        run_id="r1",
        step=0,
        state=RunState(run_id="r1", run_goal=goal, goals=[]),
    )
    manifest_path = next((tmp_path / "checkpoints" / "r1").glob("*/manifest.json"))
    games: list[_RecordingGame] = []

    def build_branch(branch: str):
        built = build_fake(tmp_path, checkpoints=True, branch=branch)
        game = _RecordingGame(built.game)
        games.append(game)
        built.run_rt.game = game
        # `open_branch` 的 reset 走存档器手里的那个 game 引用，两处都要换。
        assert built.run_rt.checkpointer is not None
        built.run_rt.checkpointer.game = game
        return built.run_rt

    opened = open_branch(manifest_path, build_branch)

    assert opened.pre_run.goals == []
    assert games[0].tasks == [start_task_for("r1", goal)]
