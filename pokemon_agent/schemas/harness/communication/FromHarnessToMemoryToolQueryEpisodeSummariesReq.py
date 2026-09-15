"""`FromHarnessToMemoryToolQueryEpisodeSummariesReq`：harness → `MemoryTool` 的跨局摘要读取请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryEpisodeSummariesReq(BaseModel):
    """**按元数据等值过滤取跨局摘要**（0914 定案）。

    conditions：字段→值，AND 取交集。**字段名与取值都由调用方定，这一层不解释**——
    能筛哪些字段由写入侧（`MemoryTool.store_episode_summary` 组装的 metadata）决定，
    当前是 `run_id` / `episode_id` / `success` / `quality_score` / `scene`。
    空字典 = 不过滤、全取（合法用法，不是错误输入）。

    **原先的 `scene`/`query`/`limit`/`run_id` 四件套已删（0914）**：场景通配匹配、
    相关性排序、候选上限、条数截断、跨 run 禁令都不再住这一层——"哪些算相关、
    要几条"是消费方的领域规则，读口只认等值过滤。
    """

    conditions: dict[str, str] = Field(
        default_factory=dict, description="等值过滤条件（AND 取交集）；空 = 全取"
    )
