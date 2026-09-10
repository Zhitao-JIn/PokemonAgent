"""废弃归档回执：harness → checkpoint tool 的 void_after 交互（恢复管线的 §6 步骤回执）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToCheckpointToolVoidResp(BaseModel):
    """一次 `void_after` 的审计回执：动了什么、归档到哪、各多少条。

    trace 废弃事件**原地打 `valid=false`**（不搬走，文件原地保留）；memory 作废
    记录归档进 `memory/voided-<ts>/<kind>/`；checkpoint 废弃局归档进本类自己的
    `voided-<ts>/`。截图不参与废弃处理（event_id 永远递增，重跑零撞名）。
    """

    run_id: str = Field(description="签名三元组之一")
    episode_id: str = Field(description="签名三元组之一（恢复目标局）")
    step: int = Field(description="签名三元组之一（恢复目标步）")
    cursor: int = Field(description="trace 游标：event_id > 它的事件全部打废弃标记")
    trace_events_voided: int = Field(description="打上 valid=false 的 trace 事件文件数")
    future_episodes: list[str] = Field(description="整体废弃的局（废弃时间线里晚于恢复点的派发）")
    step_memories_voided: int = Field(description="归档的单步记忆条数")
    object_events_voided: int = Field(description="归档的 object 交互事件条数")
    episode_memories_voided: int = Field(description="归档的跨局摘要条数（整条搬走，不按 step 筛）")
    voided_dir: str = Field(description="checkpoint 侧归档目录路径")
