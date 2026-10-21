"""统一脚本执行器消费的模拟器协议；真实与假件共用同一契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..interface import Memory, PlaceInWorld, ScreenText, TerrainMap

if TYPE_CHECKING:
    from .control_flow import ScriptResult


class WorldConsole(Protocol):
    """脚本消费的按键、帧推进、观测与组合调用契约。"""

    memory: Memory
    rom: bytes

    def press(self, key: str) -> None:
        """按下并按住一小会儿（松开在之后的帧里发生）。"""
        ...

    def tick(self, frames: int) -> None:
        """推进 N 帧。"""
        ...

    def read(self) -> ScreenText:
        """解码这一帧的屏幕缓冲。"""
        ...

    def map_id(self) -> int:
        """当前所处地图 id（RAM 直读；换图判定用）。"""
        ...

    def pos(self) -> PlaceInWorld:
        """角色当前格（全项目唯一位置表示）。"""
        ...

    def facing(self) -> str:
        """角色当前朝向（`north/south/west/east`，`FACING_BY_BYTE` 同词；读不出为空串）。"""
        ...

    def terrain(self) -> TerrainMap:
        """返回当前稳定地图的可见地形，不推进帧。

        调用方须在地图操作期间读取；地图尚未稳定时不得规划路径。
        返回网格使用当前玩家全局坐标，NPC 与障碍取自本帧内存。
        """
        ...

    def is_grass(self, x: int, y: int) -> bool:
        """这一格是不是高草丛（walk_to_adjacent 的 `entered_grass` 判定用）。"""
        ...

    def is_npc(self, x: int, y: int) -> bool:
        """这一格此刻有没有 NPC（会走，按键瞬间以实读为准——talk 的 `no_target` 复验）。"""
        ...

    def object_kind(self, x: int, y: int) -> str | None:
        """这一格的交互物 kind（人/招牌/门/物/石…，P6 起判事件用）；没有为 `None`。"""
        ...

    def scene(self) -> str:
        """当前帧的场合（`TaskScene.value`：walk/dialog/battle/…，与 `classify_scene` 同源）。"""
        ...

    def money(self) -> int:
        """现金（`read_money`，买/卖的校验读数）。"""
        ...

    def bag_count(self, item: str) -> int:
        """背包里某道具的持有数（名字逐字匹配 `read_bag` 的渲染名）。"""
        ...

    def run_script(self, name: str, args: dict[str, str | int]) -> ScriptResult:
        """执行另一条脚本并拿回它的终态报告（脚本组合：如 `buy_item` 调 `shop_buy`）。"""
        ...
