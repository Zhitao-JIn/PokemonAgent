"""`FromHarnessToMemoryToolRecallReq`：harness → `MemoryTool` 的统一回忆请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolRecallReq(BaseModel):
    """**统一回忆口**：不指定记忆种类——分族检索后融合排序（MCP 化定案 2026-09-29）。

    `conditions` 只放上下文 hint（episode_id / map_id / place / run_id），
    **不放 kind**——按 hint 分族圈定是底层规则，不是调用方的选择。
    """

    query: str = Field(default="", description="回忆什么；空 = 纯 hint 圈定（本局/本格）")
    conditions: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "上下文 hint：episode_id（圈本局 act+task）/ map_id、place"
            "（圈格 object）/ run_id（圈 episode 摘要）"
        ),
    )
    limit: int = Field(default=8, ge=1, description="融合后返回的条数上限")
