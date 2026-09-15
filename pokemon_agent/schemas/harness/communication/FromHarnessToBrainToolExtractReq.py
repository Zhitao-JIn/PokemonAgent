"""`FromHarnessToBrainToolExtractReq`：harness → `BrainTool` 的世界知识抽取请求。

**和 `SummarizeReq` 收同一类素材**（这一局过滤后的可信记录），但问的是另一个
问题：`summarize` 问"**这一局**打得怎么样"，`extract` 问"**这个世界**有什么
我之前不知道的"。

**`prompt` 不在这里**：`BrainTool.extract()` 入口处自己拼
（`prompts.extract.build_prompt(req)`）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import StepMemory


class FromHarnessToBrainToolExtractReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的抽取请求。

    entries：**已经过滤过**的可信 step 记忆，按 step 升序（拿 `verify()` 的
        `verdicts` 筛完再传——"过滤归 harness"）。从没验证过的自述里抽知识，
        等于把幻觉固化成"世界规则"，所以这一条前置条件是硬的。
    episode_id / run_id：**这条知识是从哪一局读到的**——它们是来源，不是知识的
        身份（知识跨局成立）。`BrainTool` 组装 `KnowledgeRecord` 时用它填
        `source` / `run_id` / `episode_id`。
    goal：本局目标——抽取要看"这条信息对做任务有没有用"，纯风景描写不是知识。
    images：要带的截图（base64 编码的 PNG 字符串，按 entries 去重后的顺序）。
    """

    entries: list[StepMemory]
    episode_id: str
    run_id: str
    goal: str
    images: list[str] = Field(default_factory=list)


__all__ = ["FromHarnessToBrainToolExtractReq"]
