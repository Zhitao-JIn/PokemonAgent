"""`run_plan.md` 的装配逻辑：加载、拼装、渲染，都在这一个文件里。

跟 `decide_action.py`/`judge_success.py`/`verify.py`/`summarize.py` 同一个模式
——`RunHarness` 只负责取记忆、组装 `PlanOnceReq`（`plan`/`index`/`details`/`objects`
保持结构化），struct→text 交给这里的 `build_prompt()`。

**0914 S2：素材从 trace 换成 memory**。原先这里是 `history_lines(events)`——从全量
事件流里挑 `episode_start`/`episode_end` 折出"每局一行"。现在折的是记忆，三段：

- `index_lines`：本 run **每一局一行**，取的是章（`episode_id`/`goal`/成败/步数）；
- `detail_blocks`：**少数几局的正文**（一期按确定性规则选，见
  `run/perceive`（`_pick_details`））；
- `object_lines`：本 run 涉及的地图交互事实，一条一行。

`history_blocks()` 把三段拼成 brain 认的"发生过什么"
（`Brain.plan(history=…)` 要一个 `Sequence[str]`），`build_prompt()` 把它们渲进
模板的对应占位符——**共用同一份实现**，分两份迟早漂移（一处改了措辞、另一处没改，
模型读到的历史和控制台看到的历史就不一样了）。
"""

from __future__ import annotations

from collections.abc import Sequence

from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq
from pokemon_agent.schemas.harness.domain import GoalEntry
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent
from pokemon_agent.tools.prompts.object_render import render_object_events

from . import append_human_note, load

_TEMPLATE = load("run_plan")

_DETAIL_SEPARATOR = "--- 以上每一局一行是索引；以下是其中几局的正文 ---"


def index_lines(index: Sequence[EpisodeMemory]) -> list[str]:
    """把本 run 的局索引折成**每局一行**，返回**行列表**。

    **只取来源章**（成败是 harness 的机械判定，`success` 字段），正文不进这一行
    ——那是 `detail_blocks` 的事。这正是渐进披露的第一层："全部局的骨架"。

    标签（`tags`）附在行尾供定位；没有标签就不写空括号。
    """
    lines: list[str] = []
    for memory in index:
        mark = "成功" if memory.success else "失败"
        tags = f"｜{'/'.join(memory.tags)}" if memory.tags else ""
        lines.append(f"- {memory.episode_id}: {memory.goal} → {mark}（{memory.steps} 步）{tags}")
    return lines


def detail_blocks(details: Sequence[EpisodeMemory]) -> list[str]:
    """把**被选中的那几局**渲染成正文块，返回**块列表**（一块一局）。

    用 `EpisodeMemory.render()`——它已经是"章 + 正文"的形态，且与检索打分共用
    同一份文本（`schemas/memory/datastore/episode_memory.py` 里那条"两处用同一份
    文本"的理由）。空正文的记录有 `render()` 自己说明（它看 `summary` 空不空），
    这里不特判。
    """
    return [memory.render() for memory in details]


def object_lines(objects: Sequence[ObjectFactEvent]) -> list[str]:
    """把地图交互事实渲染成**一条一行**，返回**行列表**。

    渲染本身复用 `object_render.render_object_events()`（局内检索的
    `known_objects` 段用的是同一份）——plan 与 episode 两条链看到的措辞必须一致，
    否则同一件事在"规划时"和"决策时"是两种说法。
    """
    rendered = render_object_events(objects)
    return rendered.splitlines() if rendered else []


def history_blocks(req: FromHarnessToBrainToolPlanOnceReq) -> list[str]:
    """拼出 brain `history` 参数要的"发生过什么"：索引 + 详情 + 地图事实。

    **唯一真源**：`build_prompt()` 与 `BrainTool.plan()` 都调这个函数，谁也不
    自己拼一遍。
    """
    blocks = index_lines(req.index)
    details = detail_blocks(req.details)
    objects = object_lines(req.objects)
    if details:
        blocks = [*blocks, "", _DETAIL_SEPARATOR, "", *details]
    if objects:
        blocks = [*blocks, "", "--- 地图交互事实（跨局共池，一行一条）---", "", *objects]
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
        lines.append(f"[{i}] {entry.status.value:<9}{overturned} {entry.task.goal}{tried}{note}")
    return lines


def build_prompt(req: FromHarnessToBrainToolPlanOnceReq) -> str:
    """拼出这一轮 `plan` 用的完整 prompt。"""
    index = index_lines(req.index)
    details = detail_blocks(req.details)
    objects = object_lines(req.objects)
    goals = goals_lines(req.plan)
    return append_human_note(
        _TEMPLATE.render(
            index="\n".join(index) if index else "（本 run 还没有跑完任何一局）",
            details="\n\n".join(details) if details else "（这一版不附任何一局的正文）",
            objects="\n".join(objects) if objects else "（还没有任何地图交互事实）",
            goals="\n".join(goals) if goals else "（空表）",
            max_push=req.max_push,
        ),
        req.human_note,
    )


__all__ = [
    "build_prompt",
    "detail_blocks",
    "goals_lines",
    "history_blocks",
    "index_lines",
    "object_lines",
]
