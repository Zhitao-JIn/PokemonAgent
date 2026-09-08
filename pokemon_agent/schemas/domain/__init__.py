"""domain schema 包：跨层传递的领域实体。枚举、跨模块常量、纯函数集中在这里。

`Scene`/`Overlay` 受 append-only 约束（机制三的 `(state-key, action) -> value`
一旦开始积累，枚举值只能增不能改）。

本文件同时是统一出口：`domain/` 下各文件的公开实体从这里 re-export，
消费方只写 `from pokemon_agent.schemas.domain import X`，不深到模块文件。
"""

from __future__ import annotations

__all__ = [
    "ActionFromBrain",
    "ActionSegmentFromBrain",
    "ActionSpaceForBrain",
    "BUTTON_FACING",
    "FACING_STEP",
    "GoalForBrain",
    "INTERACT_KEY",
    "LandmarkInWorld",
    "MAP_CHARS",
    "MAX_RATIONALE",
    "MAX_TIMES",
    "ModelCall",
    "OVERLAY_ACTIONS",
    "ObservationFromWorld",
    "Overlay",
    "PLAYER_CELL",
    "PLAYER_MARK",
    "PlaceInWorld",
    "Scene",
    "TERRAIN_MEANING",
    "TaskForHarness",
    "terrain_legend",
]
from enum import Enum

BUTTON_FACING: dict[str, str] = {
    "up": "north",
    "down": "south",
    "left": "west",
    "right": "east",
}
"""方向键 → 朝向。**这张表回答的是"这一步往哪个方向按了"，不是"现在面朝哪"。**

后者从内存直接读（`ram.read_facing`，精灵表 +9），不用按键推——
开局和过场之后朝向未知，且朝向不在存档里、checkpoint 恢复不出来，
按键推的值在这两个场景都是错的；读内存两个洞都不存在。

留着这张表是因为工具层要用它算"这一步走的是哪个方向"（语义记忆的 attempts 键），
那是关于**动作**的问题，不是关于状态的。
"""

FACING_STEP: dict[str, tuple[int, int]] = {
    "north": (0, -1),
    "south": (0, 1),
    "west": (-1, 0),
    "east": (1, 0),
}
"""朝向 → 全局坐标的位移。**`a` 作用在面朝的那一格上**，所以要拿这张表算出
"我刚才是在跟谁互动"。y 向下增大，和 `walk_map` 的行号一致。"""

INTERACT_KEY = "a"
"""哪个键算"互动"。`a` 作用在**面朝的那一格**上：对着人说话、对着招牌看字、
对着门进去。这是游戏的规则，不是策略。

放在这里而不是工具层，理由和 `BUTTON_FACING` 一样——**两处都要用**：
工具层拿它判"这一步是不是在跟谁互动"，world 拿它把连按夹成一次
（`a` 的收益全在中间那几帧上，连按会把它们整个吃掉）。
两边各写一个 `"a"` 字面量不会报错，只会在有人改动时静默分叉。
"""

KIND_DOOR, KIND_SIGN, KIND_PERSON = "门", "招牌", "人"
"""地标的三种类型。**下半部分那组 `DOOR/SIGN/PERSON` 是地图上的字符 `D/S/N`，
不是这个**——两组名字撞过一次，症状是门的分支静默不生效。"""


class Scene(str, Enum):
    """你在什么场合。决定**要读哪些字段**。"""

    FIELD = "field"  # 野外：城镇、路线，可自由走动
    INDOOR = "indoor"  # 室内：研究所、民宅、道馆内部
    BATTLE = "battle"  # 战斗中
    MENU = "menu"  # 系统菜单：START 菜单 / 背包 / 精灵列表 / 状态页
    SHOP = "shop"  # 商店买卖界面
    TRANSITION = "transition"  # 过场：黑屏、进出门、白闪


class Overlay(str, Enum):
    """屏幕上盖着什么等你操作。决定**可以按什么键**。"""

    NONE = "none"  # 没有弹出层，直接操作角色
    DIALOG = "dialog"  # 对话框：一段文本等你推进
    CHOICE = "choice"  # 选择框：一组选项 + 光标


# ---- 两张表：二元组的收益就兑现在这里 ----

OVERLAY_ACTIONS: dict[Overlay, tuple[str, ...]] = {
    Overlay.NONE: ("up", "down", "left", "right", "a", "start"),
    Overlay.DIALOG: ("a",),  # 方向键无效，只能推进
    # 掩码取**并集**而不是交集：`choice` 底下盖着两种物理布局——商店/对话的
    # yes-no 是竖排，战斗行动菜单是 2×2（FIGHT PKMN / ITEM RUN），
    # 任取交集都会让某种布局的按键物理上够不着。
    # **给不出正确的键，换来的不是大脑不动，是它编一个能解释掩码的世界模型。**
    # 代价是竖排选择框里左右成了空按键（按下去画面不变，白费一步）——
    # 这个代价可见（记忆里前后两份快照摆在一起，字段一模一样），
    # 而够不着的选项不可见。
    Overlay.CHOICE: ("up", "down", "left", "right", "a", "b"),
}
"""动作掩码**只看 overlay**，与 scene 无关。

这就是拆成二元组最直接的回报：三条规则覆盖所有场合，
而不是每个"场合 × 叠加层"的组合各写一遍。

代价在 `CHOICE` 上付：它盖着的两种布局按键需求不同，掩码取的是**并集**而不是
交集——宁可多给两个当帧无效的键，也不能少给一个够得着某个选项的键。
真要按 scene 收窄，就得把这张表的键从 `Overlay` 改成 `(Scene, Overlay)`，
`BUTTON_HELP` 跟着一起改；那是另一笔账，不在这条注释解决。
"""

GRID_COLS, GRID_ROWS = 10, 9
"""屏幕上有几列几行格子。160/16 = 10，144/16 = 9。"""

PLAYER_CELL = (4, 4)
"""主角在屏幕上的格子坐标 `(col, row)`，**是个常量**。

宝可梦红的镜头锁死在主角身上，所以他在屏幕上的位置永远不变——28 张真实截图
（野外、室内、有无对话框）无一例外。

这一条把感知任务降了一个维度：**模型不需要定位主角**，只需要读格子内容。
它同时提供一个免费的自检位——模型把 `@` 放到别处，说明它的坐标系整个是错的，
这一帧判废重试，不必等 agent 撞墙才发现。
"""

PLAYER_MARK = "@"

DOOR, SIGN, PERSON, GRASS = "D", "S", "N", "G"

TERRAIN_MEANING: dict[str, str] = {
    ".": "能走",
    "G": "草丛，能走，走进去会遇野生宝可梦",
    "D": "门 / 入口 / 楼梯，走进去会切换到另一张地图",
    "S": "招牌或可调查物，走不过去；面朝它按 A 可以看",
    "N": "人，走不过去；面朝它按 A 可以对话",
    "#": "墙 / 树 / 建筑 / 水面，走不过去",
    "@": "你自己。图上标 @ 的那一格就是 `where` 那一行给的坐标",
}
"""地形符号的含义。**每一个都来自模拟器内存，没有一个是认出来的。**

    .  #   ← tile id 查 tileset 的可通行表（游戏自己的 CheckTilePassable）
    G      ← tileset 头里的 wGrassTile
    D      ← 地图头的 warp 表（还带着通往哪张地图）
    S      ← 地图头的 sign 表
    N      ← 精灵表 wSpriteStateData1
    @      ← 常量，镜头锁在主角身上

这就是这一版和前三版的根本差别：视觉模型反复读错的东西（墙认成门、窗户认成人），
在这里**根本不存在"认"这个动作**。

这份 dict 同时是 prompt 里的图例来源（`terrain_legend()`），两边共用一份——
各写一份必然漂移，而模型和大脑用两套字典这种错不会报错，只会静默互相误解。
"""

MAP_CHARS = frozenset(TERRAIN_MEANING)


def terrain_legend() -> str:
    """渲染成 prompt 和动作说明里的图例。"""
    return "\n".join(f"- `{ch}` {text}" for ch, text in TERRAIN_MEANING.items())


# ---- 动作契约的跨模块常量（原 tools 包） ----

MAX_RATIONALE = 3
"""一个动作最多带几条论据。

抽成常量是因为它有两个执行点——`ActionFromBrain` 的字段约束（数据契约）和 `Brain._parse`
（外部输入校验）。两处必须同源，否则模型给 4 条时会得到一个自相矛盾的系统：
解析器放行、构造时炸。
"""


MAX_TIMES = 8
"""一段最多连按几次。

**同一个数有两个执行点**——这里的字段约束（数据契约）和 `Brain._parse`
（外部输入校验），所以必须同源，理由同 `MAX_RATIONALE`。

上限存在的理由：模型会写 `"times": "100"`。连按期间 agent 看不见中间状态，
撞墙了也会把剩下几次按完——这是时序抽象的经典取舍，次数是宏动作（机制二）的原始形态。

收益是**省感知调用**：走 5 格从 5 次 VLM 调用变成 1 次。
感知是每步都花钱的那一项，这一下把成本和延迟都砍到五分之一。
"""

from .action_from_brain import ActionFromBrain, ActionSegmentFromBrain  # noqa: E402
from .action_space_for_brain import ActionSpaceForBrain  # noqa: E402
from .goal_for_brain import GoalForBrain  # noqa: E402
from .model_call import ModelCall  # noqa: E402
from .observation_from_world import ObservationFromWorld  # noqa: E402
from .place_in_world import LandmarkInWorld, PlaceInWorld  # noqa: E402
from .task_for_harness import TaskForHarness  # noqa: E402
