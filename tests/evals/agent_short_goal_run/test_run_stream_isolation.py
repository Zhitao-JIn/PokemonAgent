"""`RunStream.load` 的证据隔离：一个落盘根里平铺多个 run，读侧只取本 run（636）。

**为什么这个文件值钱**：633 把 run 粒度样本的取局口径改成"本执行线全部局"，前提是
`load` 已经把范围圈到本 run。local 后端的落盘根是**多 run 平铺的一个目录**，而
`TraceTool.read_events()` 空 meta 读全量——不按 `meta.run_id` 过滤，别的 run 的局与帧
就会串进本 run 的证据链（实测：传入不存在的 run id 仍读回整份账并判通过）。

这里落真账：`TraceTool` 写盘（真封套、真渲染），只用 `tmp_path` 与假观测，
不碰模拟器、不调模型。
"""

from __future__ import annotations

import pathlib
from typing import Any

from test_evals_checks import sample

from evals.agent_short_goal_run.scorer import RunStream, mechanical_scorer
from pokemon_agent.brain import Task
from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.world import Facts, TaskObservation, TaskScene


def _append(
    tool: TraceTool,
    kind: str,
    *,
    episode_id: str,
    meta: dict[str, Any] | None = None,
    **fields: Any,
) -> None:
    """记一笔带签名的最小账（`meta` 四件由这里补齐，`run_id` / `branch` 由 tool 盖）。"""
    tool.append(
        FromHarnessToTraceToolAppendReq(
            kind=kind,
            meta={
                "source": "test",
                "episode_id": episode_id,
                "task_id": "",
                "step": 0,
                **(meta or {}),
            },
            **fields,
        )
    )


def _write_run(root: pathlib.Path, run_id: str, *, branch: str = "main") -> None:
    """一个 run 的最小落盘账：一局开局账 + 一帧。"""
    tool = TraceTool.build(run_id=run_id, trace_root=root, branch=branch)
    _append(
        tool,
        TraceKind.EPISODE_START,
        episode_id=f"{run_id}-ep1",
        task=Task(
            task_id=f"{run_id}-g1",
            goal="换一条路线",
            success_criteria="进入建筑",
            max_steps=3,
        ),
    )
    _append(
        tool,
        TraceKind.SENSE_FRAME,
        episode_id=f"{run_id}-ep1",
        obs=TaskObservation(facts=Facts(overlay=Facts.Overlay.NONE), step=0, scene=TaskScene.WALK),
    )


def test_load_returns_only_the_requested_run(tmp_path: pathlib.Path) -> None:
    """同一落盘根里两个 run 平铺：load(A) 的事件、局、帧都不含 B。"""
    _write_run(tmp_path, "run-a")
    _write_run(tmp_path, "run-b")

    stream = RunStream.load(tmp_path, "run-a")

    assert {event.meta.run_id for event in stream.events} == {"run-a"}
    assert stream.run_episodes() == ["run-a-ep1"]
    assert [frame.episode_id for frame in stream.frames()] == ["run-a-ep1"]
    assert stream.episodes_for("run-b-g1") == []


def test_an_unknown_run_id_reads_nothing_and_is_unjudgeable(tmp_path: pathlib.Path) -> None:
    """不存在的 run id 读回空账，机械判据给 unjudgeable（不是拿别的 run 的账判通过）。"""
    _write_run(tmp_path, "run-a")

    stream = RunStream.load(tmp_path, "run-missing")

    assert stream.events == []
    assert mechanical_scorer()(stream, sample("map_changed")).outcome == "unjudgeable"
