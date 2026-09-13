"""`FromHarnessToBrainToolSummarizeReq`：harness → `BrainTool` 的蒸馏请求。

**`entries` 只装过滤过的可信记录**——调用方拿 `verify()` 的 `verdicts`
自己筛完再传进来（"过滤归 harness"，这样想怎么用就怎么用）。
**`prompt` 不在这里**：`BrainTool.summarize()` 入口处自己拼
（`prompts.verify_and_summarize.build_summarize_prompt(req)`）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import StepMemory


class FromHarnessToBrainToolSummarizeReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的蒸馏请求。

    entries：**已经过滤过**的可信 step 记忆，按 step 升序。至少要有一条
        （一条可信的都没有时，调用方不该往下走）。
    episode_id / run_id：坐标，`BrainTool` 组装 `EpisodeMemory` 要用——大脑
        不知道自己在哪一局。
    goal：本局目标（写摘要要用）。
    success：这一局是否成功完成。
    steps：实际完成步数。
    max_steps：最大允许步数。
    images：要带的截图（base64 编码的 PNG 字符串，按 entries 去重后的顺序）。

    **`prompt` 不是本模型的字段**（0913 删）。
    """

    entries: list[StepMemory]
    episode_id: str
    run_id: str
    goal: str
    success: bool
    steps: int
    max_steps: int
    images: list[str] = Field(default_factory=list)
