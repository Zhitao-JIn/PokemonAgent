"""`FromHarnessToBrainToolChooseOnceResp`：`BrainTool` → harness 的决策响应。

**这里的 `calls` 是整条重试链的账**：按尝试顺序排着每一次的 `ModelCall`
（失败的那几次和最后成功的那次都在），每条账的 `payload["attempt"]` 由
`BrainTool` 的重试循环盖。调用方据此一步落账，不必自己维护 `ModelCallLog`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Action

from .ModelCall import ModelCall


class FromHarnessToBrainToolChooseOnceResp(BaseModel):
    """`BrainTool.choose()` 交回给 harness 的决策结果。

    **拿不到结果时抛 `MaxRetriesExceeded`**（整条账在异常里），本类型
    只表达成功的一侧——所以 `calls` 与 `action` 都是必有的。
    """

    action: Action = Field(description="这次尝试解析出的合法动作（已规范化）")
    calls: list[ModelCall] = Field(
        min_length=1, description="整条重试链的账，按尝试顺序，最后一个是成功那次"
    )
