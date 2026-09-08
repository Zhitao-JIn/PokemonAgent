"""废弃归档报告：checkpoint tool → harness（恢复管线的 §6 步骤回执）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromCheckpointToolToHarnessVoidReport(BaseModel):
    """一次 `void_after` 的审计回执：动了什么、归档到哪、各多少条。

    数据本身进 `voided-<ts>/` 归档目录（供审计），本报告只记数与路径。
    """

    run_id: str = Field(description="签名三元组之一")
    episode_id: str = Field(description="签名三元组之一（恢复目标局）")
    step: int = Field(description="签名三元组之一（恢复目标步）")
    cursor: int = Field(description="trace 游标：event_id > 它的事件全部废弃")
    trace_events_voided: int = Field(description="归档的 trace 事件行数")
    future_episodes: list[str] = Field(description="整体废弃的局（废弃时间线里晚于恢复点的派发）")
    step_memories_voided: int = Field(description="截断的单步记忆条数")
    object_events_voided: int = Field(description="截断的 object 交互事件条数")
    screenshots_voided: int = Field(description="归档的截图文件数")
    voided_dir: str = Field(description="归档目录路径")
