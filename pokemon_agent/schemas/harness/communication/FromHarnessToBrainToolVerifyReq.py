"""`FromHarnessToBrainToolVerifyReq`：harness → `BrainTool` 的校验请求。

**只装素材**——`BrainTool.verify()` 入口处自己拼 prompt
（`prompts.verify.build_prompt(req)`）。harness 不碰 prompt。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.schemas.memory import StepMemory


class FromHarnessToBrainToolVerifyReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的校验请求。

    entries：本局全部 step 记忆，按 step 升序，全量（未过滤）——**过滤发生在
        校验之后**（拿 `verdicts` 自己筛），这里必须是全量。**要带的截图也由
        `BrainTool.verify()` 从这同一批 entries 取**（`dedup_snapshots()`，
        0915 130 收权）——信封不另开 images 通道。
    goal：本局目标（校验 prompt 会交代"这一局在做什么"，判定才有的放矢）。
    knowledge：检索到的领域知识文本，校验时要用（可能为空，渲染进 prompt）。

    **`prompt` 不是本模型的字段**（0913 删）。
    **`images` 同样不是本模型的字段**（0915 130 删）：拼图与拼 prompt 同在
    tool 入口。
    """

    entries: list[StepMemory]
    goal: str
    knowledge: str = ""
