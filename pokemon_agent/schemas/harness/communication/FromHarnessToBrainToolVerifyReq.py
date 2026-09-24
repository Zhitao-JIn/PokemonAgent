"""`FromHarnessToBrainToolVerifyReq`：harness → `BrainTool` 的校验请求。

**只装素材**——`BrainTool.verify()` 入口处自己拼 prompt
（`prompts.verify.build_prompt(req)`）。harness 不碰 prompt。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.schemas.memory import ActMemory, TaskMemory


class FromHarnessToBrainToolVerifyReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的校验请求。

    entries：待标记的素材，**全量（未过滤）**——过滤发生在校验之后（拿
        `verdicts` 自己筛），这里必须是全量。两级复用同一个信封（0923 192）：
        task 层 `task_done` 装本 task 的 ActMemory（对照 task goal），episode
        层 `verify_task_memories` 装本局的 TaskMemory（对照本局 goal）；一次
        调用只装一种（两者渲染方式不同，不混装）。**要带的截图也由
        `BrainTool.verify()` 从这同一批 entries 取**——信封不另开 images 通道。
    goal：对照的目标（校验 prompt 会交代"在做什么"，正/负样本才有的放矢）。
    knowledge：检索到的领域知识文本，校验时要用（可能为空，渲染进 prompt）。

    **`prompt` 不是本模型的字段**（0913 删）。
    **`images` 同样不是本模型的字段**（0915 130 删）：拼图与拼 prompt 同在
    tool 入口。
    """

    entries: list[ActMemory | TaskMemory]
    goal: str
    knowledge: str = ""
