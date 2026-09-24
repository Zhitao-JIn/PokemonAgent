"""`decompose.md` 的装配逻辑：episode 级拆解（目标 → 任务链）的 prompt 拼装。

`context_lines()` 是素材行的唯一真源：`build_prompt()` 与 `BrainTool` 传给
brain 的 `context` 都调它。模板正文待定稿（见 `calls/decompose.md`）。
"""

from __future__ import annotations

from collections.abc import Sequence

from pokemon_agent.schemas.harness import FromHarnessToBrainToolDecomposeReq
from pokemon_agent.schemas.harness.domain import TaskEntry
from pokemon_agent.world import terrain_legend

from . import append_human_note, load

_TEMPLATE = load("decompose")


def task_table_lines(table: Sequence[TaskEntry]) -> list[str]:
    """把本局任务表渲成每条一行：task_id、版次、定案状态（人审推翻的标出来）、目标、理由。

    **成败以这张表为准**——TaskMemory 里记的是机器判定，人审推翻过的以这里为准。
    拆解与 episode 判定共用这一个渲染（唯一真源）。
    """
    lines: list[str] = []
    for entry in table:
        overturned = "（人审推翻）" if entry.overturned else ""
        note = f" · {entry.note}" if entry.note else ""
        lines.append(
            f"[{entry.task.task_id} · 第{entry.round}版] {entry.status.value}{overturned} "
            f"{entry.task.goal}{note}"
        )
    return lines


def context_lines(req: FromHarnessToBrainToolDecomposeReq) -> list[str]:
    """当前帧 + 本局任务表 + 本局已跑 task 的记忆 + 跨局摘要，渲成素材行。"""
    lines = ["## 当前画面", req.observation.render()]
    if req.task_table:
        lines += ["", "## 本局任务表（成败以此为准）", *task_table_lines(req.task_table)]
    if req.task_memories:
        lines += ["", "## 本局已跑的 task", *(m.render() for m in req.task_memories)]
    if req.episode_memories:
        lines += ["", "## 本 run 的局摘要", *(m.render() for m in req.episode_memories)]
    return lines


def build_prompt(req: FromHarnessToBrainToolDecomposeReq) -> str:
    """拼出拆解这次调用要问的完整 prompt；人类插话拼在最末尾。"""
    return append_human_note(
        _TEMPLATE.render(
            goal=req.goal.goal,
            criteria=req.goal.criteria,
            context="\n".join(context_lines(req)),
            max_tasks=req.max_tasks,
            terrain_legend=terrain_legend(),
        ),
        req.human_note,
    )
