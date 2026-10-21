"""run 规划素材渲染：本 run 全部局正文、过往 run 一行背景与地图事实。

history_blocks 与 build_prompt 共用详情、背景与事实的渲染函数。
知识和当前画面各有独立占位符，图片只走 images 通道。
"""

from __future__ import annotations

from collections.abc import Sequence

from pokemon_agent.direct.prompts.object_render import render_object_events
from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq
from pokemon_agent.schemas.harness.domain import GoalEntry
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent, RunMemory

from . import append_human_note, load
from .last_judge import last_judge_lines

_TEMPLATE = load("run_plan")


def detail_blocks(details: Sequence[EpisodeMemory]) -> list[str]:
    """把本 run 全部局按执行顺序渲染成正文块，返回**块列表**（一块一局）。

    用 `EpisodeMemory.render()`——它已经是"章 + 正文"的形态，且与检索打分共用
    同一份文本（`schemas/memory/datastore/episode_memory.py` 里那条"两处用同一份
    文本"的理由）。空正文的记录有 `render()` 自己说明（它看 `summary` 空不空），
    这里不特判。
    """
    return [memory.render() for memory in details]


def run_index_lines(memories: Sequence[RunMemory]) -> list[str]:
    """过往 run 每条仅渲染 index_line，背景不充当本 run 的经历。"""
    return [memory.index_line() for memory in memories]


def object_lines(objects: Sequence[ObjectFactEvent]) -> list[str]:
    """把地图交互事实渲染成**一条一行**，返回**行列表**。

    渲染本身复用 `object_render.render_object_events()`（局内检索的
    `known_objects` 段用的是同一份）——plan 与 episode 两条链看到的措辞必须一致，
    否则同一件事在"规划时"和"决策时"是两种说法。
    """
    rendered = render_object_events(objects)
    return rendered.splitlines() if rendered else []


def history_blocks(req: FromHarnessToBrainToolPlanOnceReq) -> list[str]:
    """依次拼全部局详情、过往 run 一行背景、地图交互事实；与 prompt 同源。"""
    blocks = detail_blocks(req.details)
    background = run_index_lines(req.run_index)
    objects = object_lines(req.objects)
    if background:
        blocks += ["", "## 过往 run(背景,一行一条,不是本 run 的经历)", *background]
    if objects:
        blocks += ["", "--- 地图交互事实（跨局共池，一行一条）---", *objects]
    return blocks


def goals_lines(plan: Sequence[GoalEntry]) -> list[str]:
    """把**目标表**渲染成每目标一行，返回行列表。

    行首是**表内序号**（模型点名一条要用它）、状态、目标；人审推翻过的定案标"（人审推翻）"；
    `note`（失败/放弃/推翻的理由）附在行尾——它就是"教训"那一栏，模型读表时最该看见的东西。

    顺序**照表序**：表序 = 派发顺序（`dispatch` 取第一条 `PENDING`），
    **不是**旧栈那种"表末最先做"——`run_plan.md` 里那段"最先做的排在列表最后"
    已随 LIFO 一起退役。
    """
    lines: list[str] = []
    for i, entry in enumerate(plan):
        overturned = "（人审推翻）" if entry.overturned else ""
        tried = f" · 已试 {entry.attempts} 次" if entry.attempts else ""
        note = f" · {entry.note}" if entry.note else ""
        lines.append(
            f"[{i}] {entry.status.value:<9}{overturned} {entry.task.goal} "
            f"· 验收={entry.task.success_criteria} · 预算={entry.task.max_steps} tasks "
            f"· ID={entry.task.task_id} "
            f"· 最近执行={entry.last_episode_id or '尚未派发'}{tried}{note}"
        )
    return lines


def build_prompt(req: FromHarnessToBrainToolPlanOnceReq) -> str:
    """拼出这一轮 `plan` 用的完整 prompt。"""
    background = run_index_lines(req.run_index)
    details = detail_blocks(req.details)
    objects = object_lines(req.objects)
    goals = goals_lines(req.plan)
    judged = last_judge_lines(req.last_judge) if req.last_judge is not None else []
    return append_human_note(
        _TEMPLATE.render(
            details="\n\n".join(details) if details else "（本 run 还没有跑完任何一局）",
            run_index="\n".join(background) if background else "（没有过往 run）",
            knowledge="\n\n".join(req.knowledge) if req.knowledge else "（没有检索到相关知识）",
            observation=req.observation.render()
            if req.observation is not None
            else "（当前画面尚未取得）",
            objects="\n".join(objects) if objects else "（还没有任何地图交互事实）",
            goals="\n".join(goals) if goals else "（空表）",
            last_judge="\n".join(judged) if judged else "（还没有判定过）",
            max_push=req.max_push,
            parent_goal=req.run_goal.goal,
            parent_criteria=req.run_goal.criteria,
            planning_budget=str(req.remaining_planning_rounds)
            if req.remaining_planning_rounds is not None
            else "未提供",
            execution_order=str(req.execution_order),
        ),
        req.human_note,
    )


__all__ = [
    "build_prompt",
    "detail_blocks",
    "goals_lines",
    "history_blocks",
    "run_index_lines",
    "object_lines",
]
