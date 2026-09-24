"""`summarize_task.md` 的装配逻辑：task 级蒸馏的 prompt 拼装。

与 `summarize.py` 同构：原料是本 task 区间的全部 ActMemory + verify 的正/负标注，
打标规则共用 `summarize.labeled_blocks()`。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import FromHarnessToBrainToolSummarizeTaskReq
from pokemon_agent.schemas.memory import render_sequence

from . import load
from .summarize import labeled_blocks

_TEMPLATE = load("summarize_task")


def history_blocks(req: FromHarnessToBrainToolSummarizeTaskReq) -> list[str]:
    """本 task 的素材块（去重相邻快照 + 正负打标）。`build_prompt` 与 `BrainTool` 共用。"""
    return labeled_blocks(render_sequence(list(req.entries)), req.verdicts)


def build_prompt(req: FromHarnessToBrainToolSummarizeTaskReq) -> str:
    """拼出 task 蒸馏这次调用要问的完整 prompt。前置条件：`req.entries` 非空。"""
    return _TEMPLATE.render(
        goal=req.goal,
        task_id=req.task_id,
        steps_text="\n\n".join(history_blocks(req)),
        result=("目标达成" if req.success else "目标未达成")
        + f"（{req.termination.value}）；判定依据：{req.judge_reason or '（无）'}",
        steps=req.steps_used,
        max_steps=req.max_steps,
    )
