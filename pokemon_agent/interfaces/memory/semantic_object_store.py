"""语义记忆（object）的存储接口：一格物体交互事件流的读写端。

**memory 只做读写与索引**（分层原则见 AGENTS.md 四）：这个接口收发的是
`ObjectFactEvent`——harness 判定层构造好的事件，存储层不理解游戏语义、
不做任何折叠或派生。"这扇门通向哪""这格说过什么"这类问题由消费方
（prompt 渲染）对事件序列现算。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.datastore import ObjectFactEvent
from pokemon_agent.schemas.domain import PlaceInWorld


@runtime_checkable
class SemanticObjectReader(Protocol):
    """语义记忆（object）的读端：按格 / 按图过滤出交互事件。"""

    def query(self, place: PlaceInWorld) -> list[ObjectFactEvent]:
        """取这一格的全部交互事件，按 step 升序。

        place：要查的物体格。
        后置条件：没有记录返回空列表；按 step 升序、同 step 按写入顺序。
        """
        ...

    def query_map(self, map_id: int, before_step: int | None = None) -> list[ObjectFactEvent]:
        """取这张地图上的全部交互事件，按 step 升序。

        map_id：地图编号。
        before_step：只取 step 严格小于它的事件；None = 不过滤。
            "检索不读未来"本来就是正确语义——正常运行的检索只该看到
            已完成步的记忆，恢复场景白捡同一条保证。
        """
        ...


@runtime_checkable
class SemanticObjectWriter(Protocol):
    """语义记忆（object）的写端：追加事件 + 恢复时的截断。"""

    def append(self, events: list[ObjectFactEvent]) -> None:
        """追加一批交互事件：先落盘一行（写穿），再进索引。

        events：harness 判定层构造好的事件，同批保持顺序。
        前置条件：每个事件的 step ≥ 其所在局文件里已有的最大 step
            （等于容忍崩溃窗口的重复，恢复时的截断负责清理）。
        后置条件：落盘与索引同时生效；进程重启后事件仍在。
        """
        ...

    def truncate(self, episode_id: str, step: int) -> None:
        """把这一局 step 大于 `step` 的事件全部删掉（checkpoint 恢复的截断）。

        episode_id：要截断的局。
        step：恢复点；保留 step <= step 的事件。
        后置条件：该局事件流里不存在 step > step 的记录（幂等——没有就什么都不做）。
        """
        ...


@runtime_checkable
class SemanticObjectStore(SemanticObjectReader, SemanticObjectWriter, Protocol):
    """语义记忆（object）存储的并集。"""
