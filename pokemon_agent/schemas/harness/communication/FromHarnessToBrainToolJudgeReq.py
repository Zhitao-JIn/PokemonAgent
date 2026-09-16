"""`FromHarnessToBrainToolJudgeReq`：harness → `BrainTool` 的判定请求。

**只装素材**（目标、历史、截图）——`BrainTool` 自己拼 prompt（`prompts.judge_success`
的 `build_prompt()`）、自己渲染 `history` 文本，再交给大脑。harness 不碰 prompt
（0913 定案："拼 prompt"与"问模型"都在 tool 一处的入口上，不分散两个地方）。
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from pokemon_agent.brain.interface import Goal
from pokemon_agent.schemas.memory import StepMemory


class FromHarnessToBrainToolJudgeReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的判定请求。

    goal：要判的目标。
    history：本局最近几步（含 rationale，prompt 渲 `$history` 时按 `reason=False`
        滤掉——判定看"发生了什么"，不看决策者的主张）。**要带的截图也由
        `BrainTool.judge()` 从这同一批 history 取**（`dedup_snapshots()`，
        0915 130 收权）——信封不另开 images 通道。
    human_note：人对**上一次判定**插的一句话（空串 = 没被插话）。非空时它就是
        "带话重问"的那一次——由 prompt 层拼在**最末尾**，压过上面所有规则
        （0914 控制台改造：插话的落点之一）。

    **`prompt` 不是本模型的字段**（0913 删）：它是 `BrainTool.judge()` 入口处
    调 `build_prompt(req)` 的产物，只活在那一次调用的局部——shell 与"问模型"
    共享同一个 req 这个中间态不再外露。
    **`images` 同样不是本模型的字段**（0915 130 删）：拼图与拼 prompt 同在
    tool 入口，harness 只装素材。
    """

    goal: Goal
    history: Sequence[StepMemory] = ()
    human_note: str = ""
