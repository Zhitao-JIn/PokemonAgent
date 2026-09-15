"""`FromHarnessToBrainToolVerifyReq`：harness → `BrainTool` 的校验请求。

**只装素材**——`BrainTool.verify()` 入口处自己拼 prompt
（`prompts.verify.build_prompt(req)`）。harness 不碰 prompt。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import StepMemory


class FromHarnessToBrainToolVerifyReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的校验请求。

    entries：本局全部 step 记忆，按 step 升序，全量（未过滤）——**过滤发生在
        校验之后**（拿 `verdicts` 自己筛），这里必须是全量。
    goal：本局目标（校验 prompt 会交代"这一局在做什么"，判定才有的放矢）。
    knowledge：检索到的领域知识文本，校验时要用（可能为空，渲染进 prompt）。
    images：要带的截图（base64 编码的 PNG 字符串，按 entries 去重后的顺序）。

    **`prompt` 不是本模型的字段**（0913 删）。
    """

    entries: list[StepMemory]
    goal: str
    knowledge: str = ""
    images: list[str] = Field(default_factory=list)
