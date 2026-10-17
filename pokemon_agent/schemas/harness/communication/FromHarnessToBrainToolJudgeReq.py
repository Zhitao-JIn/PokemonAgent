"""`FromHarnessToBrainToolJudgeReq`：harness → `BrainTool` 的判定请求。

**只装素材**（目标、历史、截图）——`BrainTool` 自己拼 prompt（`prompts.judge_success`
的 `build_prompt()`）、自己渲染 `history` 文本，再交给大脑。harness 不碰 prompt
（0913 定案："拼 prompt"与"问模型"都在 tool 一处的入口上，不分散两个地方）。
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from pokemon_agent.brain.interface import Goal
from pokemon_agent.schemas.harness.domain.task_entry import TaskEntry
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, TaskMemory
from pokemon_agent.world import TaskObservation


class FromHarnessToBrainToolJudgeReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的判定请求。

    goal：要判的目标。
    history：本 task 全部动作记忆（prompt 渲 `$history` 时与决策记忆同一渲染
        滤掉——判定看"发生了什么"，不看决策者的主张）。**要带的截图也由
        `BrainTool.judge()` 从这同一批 history 取**（`dedup_snapshots()`，
        0915 130 收权）——信封不另开 images 通道。
    task_memories：episode 层判定的素材（本局已跑 task 的记忆）；task 层留空。
    task_table：episode 层判定的素材（本局任务表——成败以表为准，含人审推翻）；另两层留空。
    episode_memories：run 层判定的素材（本 run 的局摘要）；下两层留空。
    task_index：本 episode 内此前同目标 task 的无帧背景索引，只有 task 层填写。
    episode_index：episode 层的同 run_goal 其他局背景，只用 index_line 渲染。
    observation：episode 层当前画面；task / run 层本检查点留空。
    knowledge：task / episode 层领域知识；run 层本检查点保持为空串。
    allow_interrupt：只有 task 层置真——prompt 多一段「是不是被打断了」的判法，
        判定员多回答一个 `interrupted`。另两层不问，结果里 `interrupted` 恒为假。


    **`prompt` 不是本模型的字段**（0913 删）：它是 `BrainTool.judge()` 入口处
    调 `build_prompt(req)` 的产物，只活在那一次调用的局部——shell 与"问模型"
    共享同一个 req 这个中间态不再外露。
    **`images` 同样不是本模型的字段**（0915 130 删）：拼图与拼 prompt 同在
    tool 入口，harness 只装素材。
    """

    goal: Goal
    history: Sequence[ActMemory] = ()
    task_memories: Sequence[TaskMemory] = ()
    task_table: Sequence[TaskEntry] = ()
    episode_memories: Sequence[EpisodeMemory] = ()
    task_index: Sequence[TaskMemory] = ()
    episode_index: Sequence[EpisodeMemory] = ()
    observation: TaskObservation | None = None
    knowledge: str = ""
    allow_interrupt: bool = False
