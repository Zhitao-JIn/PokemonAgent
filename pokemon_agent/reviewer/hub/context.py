"""按节展示复核快照与提案，图片只计数，实际帧按需查询。"""

import json

from pydantic import BaseModel

from pokemon_agent.schemas.harness.domain.review_context import ReviewContext, frames_of
from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory, TaskMemory
from pokemon_agent.schemas.reviewer.interaction import Ask

from ..view.render import text_without_frames


def _index_line(item: object) -> str:
    """从来源章与结构化索引生成复核台索引。"""
    if isinstance(item, (EpisodeMemory, TaskMemory, RunMemory)):
        index = item.index
        tail = (
            f"{index.headline}（keys：{'、'.join(index.keys)}；含：{'、'.join(index.evidence)}）"
            if index.headline
            else "（无正文）"
        )
    if isinstance(item, EpisodeMemory):
        return (
            f"- {item.episode_id}｜{item.goal}｜{'成功' if item.success else '未成功'}｜"
            f"{item.termination or '-'}｜{item.steps} task/{item.acts_used} 键｜"
            f"{tail}"
        )
    if isinstance(item, TaskMemory):
        return (
            f"- {item.task_id}｜{item.goal}｜{'成功' if item.success else '未成功'}｜"
            f"{item.termination or '-'}｜{item.steps_used} 键｜{tail}"
        )
    if isinstance(item, RunMemory):
        return (
            f"- {item.run_id}｜{item.run_goal}｜{item.succeeded}/{item.episodes} 局成功｜"
            f"{item.termination or '-'}｜{tail}"
        )
    raise TypeError(f"不认识的记忆类型：{type(item)!r}")


def context_sections(ctx: ReviewContext) -> dict[str, str]:
    """返回四节全文；输入不变，目标表与任务表不在大脑素材里重复出现。"""
    fields = ctx.brain_input.model_dump(mode="json", exclude={"plan", "task_table"})
    for name in ("run_index", "episode_index", "task_index"):
        if hasattr(ctx.brain_input, name):
            fields[name] = [_index_line(item) for item in getattr(ctx.brain_input, name)]
    counts = ctx.model_dump(exclude={"brain_input", "goals", "tasks"})
    return {
        "大脑输入": _pretty(fields)
        + f"\n图 {len(frames_of(ctx.brain_input))} 张，用 brain-frames 查看",
        "目标表": _pretty([entry.model_dump(mode="json") for entry in ctx.goals or []]),
        "任务表": _pretty([entry.model_dump(mode="json") for entry in ctx.tasks or []]),
        "计数": json.dumps(counts, ensure_ascii=False, indent=2),
    }


def _pretty(value: object) -> str:
    """先按结构去图，再格式化为可数行的全文。"""
    return json.dumps(json.loads(text_without_frames(value)), ensure_ascii=False, indent=2)


def context_text(ctx: ReviewContext, section: str | None = None) -> str:
    """缺省给节目录和行数；指定节则展示全文，不静默截断。"""
    sections = context_sections(ctx)
    if section is None:
        return "\n".join(f"{name}：{len(text.splitlines())} 行" for name, text in sections.items())
    if section not in sections:
        raise ValueError(f"未知节：{section}；可用：{' / '.join(sections)}")
    return text_without_frames(f"## {section}\n{sections[section]}")


def ask_text(ask: Ask) -> str:
    """展示本问的种类、提案与查询入口，不预先输出全部快照或画面。"""
    req = ask.request
    if ask.kind == "inject":
        form = req.form.model_dump(mode="json") if isinstance(req.form, BaseModel) else req.form
        title = f"{req.prompt}\n第 {req.round} 轮，AI 连续生效上限 {req.max_agent_rounds}"
    else:
        form = req.outcome.model_dump(mode="json")
        title = "请复核模型的已达成结论"
    return text_without_frames(
        f"[{ask.seq} {ask.kind}] {title}\n{text_without_frames(form)}\n"
        f"{context_text(req.context)}\n用 help 查看命令，ctx --section 查看全文"
    )
