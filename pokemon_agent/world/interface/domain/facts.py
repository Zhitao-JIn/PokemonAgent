"""世界的结构化观测事实；模型文字由prompt模块生成，冻结旧键由extra保留。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from .battle_status import BattleStatus

# **本模块在包内零依赖**：顶层只有标准库与 pydantic，`domain/__init__.py` 这个
# 聚合出口（被 `world/interface/__init__.py` 立即加载）因此可以按任意顺序装配它
# ——`observation.py` / `terrain_map.py` 都只是**单向**地从它这里拿 `Facts`。
# 所以 `Facts.Landmark` 不直接嵌 `PlaceInWorld`（那会在顶层多出一条指向同包
# `place_in_world.py` 的依赖），改存 `map_id`/`x`/`y` 三个原始字段；用得到
# `PlaceInWorld` 的地方（`.place` 属性）才在方法体里现场 `import`。


class Facts(BaseModel):
    """场景、叠加层与原始观测字段。extra仅保留冻结输入和额外事实，不生产旧文本投影。"""

    model_config = ConfigDict(extra="allow")

    class Scene(StrEnum):
        """你在什么场合。决定**要读哪些字段**。"""

        FIELD = "field"  # 野外：城镇、路线，可自由走动
        INDOOR = "indoor"  # 室内：研究所、民宅、道馆内部
        BATTLE = "battle"  # 战斗中
        MENU = "menu"  # 系统菜单：START 菜单 / 背包 / 精灵列表 / 状态页
        SHOP = "shop"  # 商店买卖界面
        TRANSITION = "transition"  # 过场：黑屏、进出门、白闪、精灵进化动画
        NAMING = "naming"  # 起名字母键盘：给主角/对手/精灵起名字
        MAP_VIEW = "map_view"  # 区域总览地图：TOWN MAP 弹出的静态大地图，按 B 关闭，不能走动

    class Overlay(StrEnum):
        """屏幕上盖着什么等你操作。决定**可以按什么键**。"""

        NONE = "none"  # 没有弹出层，直接操作角色
        DIALOG = "dialog"  # 对话框：一段文本等你推进
        CHOICE = "choice"  # 选择框：一组选项 + 光标

    class Landmark(BaseModel):
        """世界里格子上的一个东西：门 / 招牌 / 人 / 物 / 石。类型和位置都来自模拟器内存。

        **没有名字。** 名字在总览画面里没有可观测的证据，只能靠走过去交互再记住——
        那正是语义记忆（object）的活（"物"除外——拾取瞬间弹出的对话文字本身就是
        名字，见
        `harness/episode/store/store_object_semantic_memory/rules.py::_pickup_or_still`）。

        **存 `map_id`/`x`/`y` 三个原始字段，不直接嵌 `PlaceInWorld`。** 不是不想用
        `PlaceInWorld`（`.place` 属性就是现拼一个给调用方）——这个模块要保持
        **包内零依赖**（见本文件顶部的说明），嵌真身会在顶层多出一条指向同包
        `place_in_world.py` 的依赖；而 Pydantic 字段的类型在类定义那一刻就要能解析，
        做不到"引用一个还没导入的类型，等以后再补"。
        """

        KIND_DOOR: ClassVar[str] = "门"
        KIND_SIGN: ClassVar[str] = "招牌"
        KIND_PERSON: ClassVar[str] = "人"
        KIND_ITEM: ClassVar[str] = "物"
        KIND_BOULDER: ClassVar[str] = "石"

        kind: str = Field(description="门 / 招牌 / 人 / 物 / 石")
        map_id: int
        x: int
        y: int

        @property
        def place(self) -> Any:  # noqa: ANN401
            """现拼一个 `PlaceInWorld`——**运行时才 `import`**，模块顶层不导入。
            返回类型标 `Any` 而不是 `PlaceInWorld`：同一个理由，这个注解如果写实名，
            `from __future__ import annotations` 关闭字符串化的地方（比如运行时
            `typing.get_type_hints()`）一样会在模块顶层触发那次导致循环导入的解析。
            """
            from .place_in_world import PlaceInWorld

            return PlaceInWorld(map_id=self.map_id, x=self.x, y=self.y)

    scene: Scene | None = Field(default=None, description="这一帧在什么场合")
    overlay: Overlay | None = Field(default=None, description="这一帧屏幕上盖着什么")
    facing: str = Field(
        default="", description="朝向（up/down/left/right），来自精灵表，不是按键推断"
    )
    landmarks: list[Landmark] = Field(
        default_factory=list,
        description="这一帧屏幕上的地标（门/招牌/人/物/石），来自 `TerrainMap.landmarks()`。"
        "**结构化原件**——判定层（`harness/episode/store/store_object_semantic_memory/"
        "rules.py`）直接用，不用再从"
        "渲染出去的文本反解一遍。空列表就是这一帧没有地标，不是漏填",
    )
    dialog_text: str = Field(default="", description="对话框里的文字，overlay=DIALOG 时才有")
    options: list[str] = Field(
        default_factory=list, description="选择框的选项列表，overlay=CHOICE 时才有"
    )
    cursor: str | None = Field(
        default=None, description="选择框光标指向的那一项原文；读不出为 None"
    )
    map_id: int | None = Field(default=None, description="当前地图编号")
    screen: str = Field(
        default="",
        description="整屏文字原样（内存里的屏幕字符缓冲逐行渲染，`screen_text.render_screen`）。"
        "与上面切好的对话 / 选项 / 光标互相校验：字段是尽力解析，这里是原样",
    )

    neighbor_cells: dict[str, str] = Field(
        default_factory=dict, description="四个方向对应的地形字符"
    )
    cells: list[str] = Field(default_factory=list, description="原始地形格；未取得地形时为空")
    option_grid: list[list[str]] = Field(default_factory=list, description="选项的行列排布")
    cursor_cell: tuple[int, int] | None = Field(default=None, description="光标所在行列，零起点")
    option_annotations: list[str] = Field(default_factory=list, description="逐选项附注原文")
    battle_status: BattleStatus | None = Field(default=None, description="战斗双方原始状态框")
    terrain_visible: bool = Field(default=False, description="旧投影是否显示地形图")

    @model_serializer(mode="wrap")
    def serialize_incremental(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """旧快照未提供的增量字段不进入其序列化结果。"""
        data = handler(self)
        for name in (
            "neighbor_cells",
            "cells",
            "option_grid",
            "cursor_cell",
            "option_annotations",
            "battle_status",
            "terrain_visible",
        ):
            if name not in self.model_fields_set:
                data.pop(name, None)
        return data

    @property
    def scene_value(self) -> str:
        """`scene` 的文本值；`scene` 为 `None` 时给空串。给只要文本、不需要结构化
        对象的调用方用（记忆检索 query、trace payload）——**唯一**做这一转换的地方，
        散落多份的话，加一种新枚举成员时容易漏改一处。"""
        return self.scene.value if self.scene is not None else ""

    @property
    def overlay_value(self) -> str:
        """同 `scene_value`，针对 `overlay`。"""
        return self.overlay.value if self.overlay is not None else ""

    def exclude(self, keys: frozenset[str]) -> Facts:
        """去掉指定的动态字段（`model_extra` 里的），返回新副本。

        用于写记忆前过滤掉不该进记忆的字段（如 `known_objects`/`knowledge`）——
        这些不是 RAM/视觉产出的"事实"，是别处临时塞进来的检索结果，本来就不该
        进 `Facts` 的具名字段，只可能以动态字段的形式出现。**直接改 `model_extra`
        字典，不走 model_dump()/model_validate() 那一趟**——去掉几个键不需要
        把整个模型序列化再反序列化一遍。
        """
        copy = self.model_copy(deep=True)
        extra = copy.model_extra
        if extra:
            for k in keys:
                extra.pop(k, None)
        return copy

    def stall_key_part(self) -> str:
        """停摆检测键里由 facts 贡献的那一段，给 `Observation.stall_key()` 用。

        只含不会因重读而变化的字段：`scene`/`overlay`/`cursor`/`dialog_text`。
        `dialog_text` **在键里**是刻意的：长对话逐句推进时，场景/光标/位置全都
        不变，唯一在变的就是对话文本；反过来，同一句对话原地重按（键不变）才是
        真的打转。它是 world 机械读出的文本，不是视觉模型的自由措辞，同帧重读稳定。
        """
        return "|".join((self.scene_value, self.overlay_value, self.cursor or "", self.dialog_text))


_OPEN_KEYS: tuple[str, ...] = ("up", "down", "left", "right", "a", "b", "start")
"""非对话帧一律给的按键：叠加层判错的代价只是多几个当帧无效的键，而不是够不着要按的键。"""

OVERLAY_ACTIONS: dict[Facts.Overlay, tuple[str, ...]] = {
    Facts.Overlay.NONE: _OPEN_KEYS,
    Facts.Overlay.DIALOG: ("a",),  # 方向键无效，只能推进；world 只在严格的对话帧上给 DIALOG
    # 掩码取**并集**而不是交集：`choice` 底下盖着两种物理布局——商店/对话的
    # yes-no 是竖排，战斗行动菜单是 2×2（FIGHT PKMN / ITEM RUN），
    # 任取交集都会让某种布局的按键物理上够不着。
    # **给不出正确的键，换来的不是大脑不动，是它编一个能解释掩码的世界模型。**
    # 代价是竖排选择框里左右成了空按键（按下去画面不变，白费一步）——
    # 这个代价可见（记忆里前后两份快照摆在一起，字段一模一样），
    # 而够不着的选项不可见。
    Facts.Overlay.CHOICE: _OPEN_KEYS,
}
"""动作掩码**只看 overlay**，与 scene 无关。

0926 起 NONE / CHOICE 都给同一组 `_OPEN_KEYS`：叠加层由屏幕解码判，队伍列表、数量框这类
界面曾被判成 DIALOG / NONE 而按不到上下键或 b。两个标签仍保留——它们告诉模型
"现在是在走路还是在选单里"（`BUTTON_HELP` 按标签给按键说明），只是不再收窄掩码。

这就是拆成二元组最直接的回报：三条规则覆盖所有场合，
而不是每个"场合 × 叠加层"的组合各写一遍。

代价在 `CHOICE` 上付：它盖着的两种布局按键需求不同，掩码取的是**并集**而不是
交集——宁可多给两个当帧无效的键，也不能少给一个够得着某个选项的键。
真要按 scene 收窄，就得把这张表的键从 `Overlay` 改成 `(Scene, Overlay)`，
`BUTTON_HELP` 跟着一起改；那是另一笔账，不在这条注释解决。
"""
