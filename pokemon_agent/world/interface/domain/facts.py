"""Facts：大脑在某一步看到的世界的结构化事实容器。

原来 `Observation.facts` 是 `dict[str, str]`——结构化的东西（地标、场景、
叠加层）先渲染成文本塞进去，判定层/记忆检索再从文本反解回来，这条弯路本身就是
错误的来源。这里只定义**一个**"总的" facts 类型：`Facts` 本身是 Pydantic 模型，
字段该是什么类型就是什么类型；`Scene`/`Overlay`/`Landmark` 都收成 `Facts` 的
**内部类**——它们只对 facts 有意义，不该在 `Facts` 之外单独存在（避免"到底是
`pokemon_agent.xxx.Overlay` 还是 `Facts.Overlay`"这种两个名字指同一个概念的混乱）。

**stringify 是 prompt 层的事**：`render()`/`items()` 是这里唯一做"结构化 → 文本"
转换的地方，且只在渲染给大脑读、或者拼检索 query 的那一刻才发生；判定层
（`harness/episode/store/store_object_semantic_memory/rules.py`）拿到的永远是
`Facts.landmarks` 这份
`list[Facts.Landmark]` 原件，不用反解任何文本。

**物理位置**：这个文件放在 `world/interface/domain/` 而不是 `schemas/world/domain/`——
`Facts` 是"世界这个子系统对外承诺的观测事实长什么样"，跟 `WorldPort`（同目录的
`world_port.py`）是同一件事的两个角度（协议 + 协议吐出来的数据形状），归一起管理。
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

# **本模块在包内零依赖**：顶层只有标准库与 pydantic，`domain/__init__.py` 这个
# 聚合出口（被 `world/interface/__init__.py` 立即加载）因此可以按任意顺序装配它
# ——`observation.py` / `terrain_map.py` 都只是**单向**地从它这里拿 `Facts`。
# 所以 `Facts.Landmark` 不直接嵌 `PlaceInWorld`（那会在顶层多出一条指向同包
# `place_in_world.py` 的依赖），改存 `map_id`/`x`/`y` 三个原始字段；用得到
# `PlaceInWorld` 的地方（`.place` 属性）才在方法体里现场 `import`。


def _display_width(text: str) -> int:
    """这段文字占几个字符宽。**中日韩字符算两格。**

    对齐要用它而不是 `len()`：标签里中英混排（`位置` 和 `my_hp` 同时出现），
    按字数补空格的话，中文那几行会短一半——而这份文本的**唯一用途**就是让大脑
    逐行对照前后两份快照，列对不齐等于把配对的活又推回给它。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


_EXTRA_ORDER: tuple[str, ...] = ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp")
"""视觉模型按 scene 自由给的那批字段（`ScreenState.fields`）里，这几个是几乎每帧
都出现、值得固定顺序的——其余没在这张表里的字段按字母序排在后面（原
`FIELD_ORDER` 的兜底规则原样保留）。"""


class Facts(BaseModel):
    """一步里"世界事实"的结构化容器：场景、叠加层、地标、位置文本、HP……

    **`extra="allow"`**：视觉模型按 scene 自由给的字段（`my_hp`/`foe_level`/`nearby`…）
    直接挂在这个模型上，不必为每个 scene 各开一个具名字段——那些字段本来就随
    scene 变化，强行都声明成具名字段只会让这个模型跟着每个新 scene 改一次。
    RAM/世界层能确定给出的那几项（`scene`/`overlay`/`landmarks`/`where`/…）才
    值得做成具名字段：它们的类型是确定的，判定层/记忆检索需要按类型访问它们，
    不是按"这份文本里有没有这个词"去猜。
    """

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

        def render(self) -> str:
            """渲染成 prompt 里那一行。"""
            return f"{self.kind} x={self.x} y={self.y}"

    scene: Scene | None = Field(default=None, description="这一帧在什么场合")
    overlay: Overlay | None = Field(default=None, description="这一帧屏幕上盖着什么")
    where: str = Field(
        default="", description="主角位置渲染成的文本（结构化的那份在 `Observation.place`）"
    )
    facing: str = Field(
        default="", description="朝向（up/down/left/right），来自精灵表，不是按键推断"
    )
    neighbors: str = Field(default="", description="四邻通行性，相对'我'的地形描述")
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
    overview: str = Field(default="", description="视觉模型对整幅画面布局的一句话描述")
    walk_map: str = Field(
        default="", description="这一帧的地形网格渲染文本，来自模拟器内存，不是模型读出来的"
    )
    map_id: int | None = Field(default=None, description="当前地图编号")

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

    def _entries(self) -> list[tuple[str, str, str]]:
        """`(字段名, 中文标签, 文本)` 列表，只含"有值"的字段，按固定顺序。

        顺序固定不是为了好看：前后两份 facts 要摆在一起给大脑比对，同一个字段在
        两份里必须出现在同一个相对位置，否则"哪一项变了"就得靠它先做一次字段配对。
        `render()`（对齐文本）和 `items()`（`- key: value` 朴素列举）共用这份顺序，
        两处措辞不一致的话，"大脑读到的"和"记忆里存的"就会变成两个不同的东西。
        """
        entries: list[tuple[str, str, str]] = []
        if self.scene is not None:
            entries.append(("scene", "场景", self.scene.value))
        if self.overlay is not None:
            entries.append(("overlay", "叠加层", self.overlay.value))
        if self.where:
            entries.append(("where", "位置", self.where))
        if self.map_id is not None:
            entries.append(("map_id", "地图", str(self.map_id)))
        if self.facing:
            entries.append(("facing", "朝向", self.facing))
        if self.neighbors:
            entries.append(("neighbors", "四邻", self.neighbors))
        if self.landmarks:
            entries.append(("landmarks", "地标", "; ".join(m.render() for m in self.landmarks)))
        if self.dialog_text:
            entries.append(("dialog_text", "对话", self.dialog_text))
        if self.options:
            entries.append(("options", "选项", " / ".join(self.options)))
        if self.cursor:
            entries.append(("cursor", "光标", self.cursor))
        extra: dict[str, Any] = self.model_extra or {}
        seen = set()
        for k in _EXTRA_ORDER:
            if k in extra and extra[k] not in (None, ""):
                entries.append((k, k, str(extra[k])))
                seen.add(k)
        for k in sorted(extra):
            if k in seen or extra[k] in (None, ""):
                continue
            entries.append((k, k, str(extra[k])))
        if self.overview:
            entries.append(("overview", "概况", self.overview))
        if self.walk_map:
            entries.append(("walk_map", "walk_map", self.walk_map))
        return entries

    def items(self) -> list[tuple[str, str]]:
        """`(字段名, 文本)` 列表——给需要 `- key: value` 这种朴素列举格式的调用方用
        （`prompts/decide_action.py` 的主 prompt）。跟字典的 `.items()` 同名，是
        故意的：调用方原来对着 `dict[str, str]` 写 `for k, v in obs.facts.items()`，
        现在对着 `Facts` 写同样的代码不用改一个字。
        """
        return [(k, text) for k, _label, text in self._entries()]

    def stall_key_part(self) -> str:
        """停摆检测键里由 facts 贡献的那一段，给 `Observation.stall_key()` 用。

        只含不会因重读而变化的字段：`scene`/`overlay`/`cursor`/`dialog_text`。
        `dialog_text` **在键里**是刻意的：长对话逐句推进时，场景/光标/位置全都
        不变，唯一在变的就是对话文本；反过来，同一句对话原地重按（键不变）才是
        真的打转。它是 world 机械读出的文本，不是视觉模型的自由措辞，同帧重读稳定。
        """
        return "|".join((self.scene_value, self.overlay_value, self.cursor or "", self.dialog_text))

    def render(self, indent: str = "  ") -> str:
        """把这份 facts 渲染成一段可读、可打分的文本，供 prompt 用。空 facts 返回空串
        （调用方——`Observation.render()`——自己决定空的时候摆什么）。
        """
        entries = self._entries()
        if not entries:
            return ""
        width = max(_display_width(label) for _k, label, _v in entries)
        lines = []
        for _k, label, body in entries:
            pad = " " * (width - _display_width(label) + 2)
            # 多行的值（`walk_map`）续行要缩进到同一列，理由同旧版：顶格续行的话
            # 图的第二行看起来就像下一个字段。
            gutter = " " * (len(indent) + width + 2)
            body = body.replace("\n", "\n" + gutter)
            lines.append(f"{indent}{label}{pad}{body}")
        return "\n".join(lines)


OVERLAY_ACTIONS: dict[Facts.Overlay, tuple[str, ...]] = {
    Facts.Overlay.NONE: ("up", "down", "left", "right", "a", "start"),
    Facts.Overlay.DIALOG: ("a",),  # 方向键无效，只能推进
    # 掩码取**并集**而不是交集：`choice` 底下盖着两种物理布局——商店/对话的
    # yes-no 是竖排，战斗行动菜单是 2×2（FIGHT PKMN / ITEM RUN），
    # 任取交集都会让某种布局的按键物理上够不着。
    # **给不出正确的键，换来的不是大脑不动，是它编一个能解释掩码的世界模型。**
    # 代价是竖排选择框里左右成了空按键（按下去画面不变，白费一步）——
    # 这个代价可见（记忆里前后两份快照摆在一起，字段一模一样），
    # 而够不着的选项不可见。
    Facts.Overlay.CHOICE: ("up", "down", "left", "right", "a", "b"),
}
"""动作掩码**只看 overlay**，与 scene 无关。

这就是拆成二元组最直接的回报：三条规则覆盖所有场合，
而不是每个"场合 × 叠加层"的组合各写一遍。

代价在 `CHOICE` 上付：它盖着的两种布局按键需求不同，掩码取的是**并集**而不是
交集——宁可多给两个当帧无效的键，也不能少给一个够得着某个选项的键。
真要按 scene 收窄，就得把这张表的键从 `Overlay` 改成 `(Scene, Overlay)`，
`BUTTON_HELP` 跟着一起改；那是另一笔账，不在这条注释解决。
"""
