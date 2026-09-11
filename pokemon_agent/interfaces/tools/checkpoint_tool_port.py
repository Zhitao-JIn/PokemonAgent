"""checkpoint 工具接口：两级 harness 的存档/恢复/废弃编排。

契约（PLAN_checkpoint v4）：签名三元组 `(run_id, episode_id, step)` 显式落在
每份 checkpoint 的 json 里；`last_event_id` 是 trace 游标——恢复的主坐标，
`event_id` 大于它的事件全部属于废弃时间线。只有一种落盘形态：`EpisodeRunState`
与当时的 `RunState` 打包进同一份 `<step>.json`（无单独的 run 级文件）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.harness import (
    FromHarnessToCheckpointToolLoadReq,
    FromHarnessToCheckpointToolLoadResp,
    FromHarnessToCheckpointToolSaveReq,
    FromHarnessToCheckpointToolVoidReq,
    FromHarnessToCheckpointToolVoidResp,
)


@runtime_checkable
class CheckpointToolPort(Protocol):
    """Harness 的 checkpoint 手：存、取（三元组定位）、废弃归档。"""

    def save(self, req: FromHarnessToCheckpointToolSaveReq) -> None:
        """存一份 checkpoint（`step/<episode_id>/<step>.*`）。

        后置条件：先世界快照后 json（json 是提交点）；中途 crash 留下的是
        上一号有效 checkpoint（恢复管线按"成对存在 + 签名匹配"识别）。
        """
        ...

    def load(
        self, req: FromHarnessToCheckpointToolLoadReq
    ) -> FromHarnessToCheckpointToolLoadResp | None:
        """按三元组取一份 checkpoint；不存在（或 state/json 不成对）返回 None。

        返回值同时带 `state_dump`（EpisodeRunState）与 `run_state_dump`
        （RunState）——调用方按自己需要的那层取，不用分两次查、也不用猜
        该读哪个文件。
        """
        ...

    def void_after(
        self, req: FromHarnessToCheckpointToolVoidReq
    ) -> FromHarnessToCheckpointToolVoidResp:
        """废弃时间线处理：trace 按 cursor 截断归档、记忆层截断、截图/存档归档。

        前置条件：调用方已完成对账（快照签名/游标合法）。
        后置条件：主前缀（event_id ≤ cursor）之外无任何残留——重跑同三元组
        不会撞名、不会读到"未来"的记忆；被废弃数据全部在 voided 归档目录。
        """
        ...
