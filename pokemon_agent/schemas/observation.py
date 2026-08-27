"""感知契约：大脑在某一步看到的世界，以及"一帧画面被解析成什么"。

`Observation`/`Place`/`Landmark` 跨层——出现在 `WorldPort`/`GameToolPort` 的签名里。
`Scene`/`Overlay`/`ScreenState`/`TerrainMap` 及以下不跨层，由 `PyBoyWorld` 产出后
就地压成 `Observation.facts` 里的字符串。放在同一个文件是因为它们是同一件事的
两个阶段——"世界被感知成什么结构"、"结构怎么变成大脑看到的那份 `Observation`"——
拆两个文件反而要在中间加一层 import 才看得出关系。

**大脑只该碰上半部分**（`Observation`/`Place`/`Landmark`）。一旦大脑开始按 `Scene`
分支，分层就名存实亡了——这条现在只能靠人守，以前是靠 `react.py` 只 import `core`
强制的，合并/拆分之后都只剩纪律。

`Scene`/`Overlay` 受 append-only 约束（机制三的 `(state-key, action) -> value`
一旦开始积累，枚举值只能增不能改）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

BUTTON_FACING: dict[str, str] = {
    "up": "north", "down": "south", "left": "west", "right": "east",
}
"""方向键 → 朝向。**这张表回答的是"这一步往哪个方向按了"，不是"现在面朝哪"。**

后者从内存直接读（`ram.read_facing`，精灵表 +9），不用推。曾经是推的——
"按过 up 就等于面朝北"，因为撞墙时人也会转过去；那个推论本身没错，
但它有两个洞：开局和过场之后朝向是未知的，而且它不在存档里，
checkpoint 恢复不出来。读内存两个洞一起消失。

留着这张表是因为工具层要用它算"这一步走的是哪个方向"（语义记忆的 attempts 键），
那是关于**动作**的问题，不是关于状态的。
"""

FACING_STEP: dict[str, tuple[int, int]] = {
    "north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0),
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


class Place(BaseModel):
    """地图上的一个格子。**这是全项目唯一的"位置"表示。**

    做成模型而不是三个散字段，是因为它现在**承载记忆的键**：
    语义记忆按 `(map_id, x, y)` 索引，那三个数必须整体传递、整体比较。
    散着传总有一天会漏掉 `map_id`，而漏掉之后两张地图上的同一个坐标会撞在一起——
    那种错不报错，只会让记忆开始张冠李戴。
    """

    map_id: int
    x: int
    y: int

    def step_toward(self, facing: str) -> Place:
        """面朝 `facing` 时，`a` 会作用到的那一格。"""
        dx, dy = FACING_STEP[facing]
        return Place(map_id=self.map_id, x=self.x + dx, y=self.y + dy)

    @property
    def key(self) -> str:
        """记忆的键。**跨 episode 稳定**——同一张地图上的同一格永远是同一个键。"""
        return f"{self.map_id}:{self.x}:{self.y}"

    def render(self) -> str:
        """渲染成进 prompt 的样子。"""
        """**全局坐标写成 `x= y=`，不用括号** —— 括号写法留给屏幕格。"""
        return f"全局坐标 地图{self.map_id} x={self.x} y={self.y}"


class Landmark(BaseModel):
    """屏幕上一个值得记住的东西：门 / 招牌 / 人。类型和位置都来自模拟器内存。

    **没有名字。** 名字在总览画面里没有可观测的证据，只能靠走过去交互再记住——
    那正是语义记忆（object）的活。
    """

    kind: str = Field(description="门 / 招牌 / 人")
    place: Place

    def render(self) -> str:
        """渲染成 prompt 里那一行。"""
        return f"{self.kind} x={self.place.x} y={self.place.y}"


class Observation(BaseModel):
    """大脑在某一步看到的世界。

    只放**大脑决策需要的**信息。原始画面、模拟器内部状态不进这里——
    那些属于 harness，大脑看不到也不该看到。
    """

    step: int = Field(description="本 episode 内的第几步，从 0 开始")
    place: Place | None = Field(
        default=None,
        description="主角所在的格子。**结构化的那一份**——"
        "`facts[\"where\"]` 是它渲染出来给模型读的文本，"
        "而记忆的键要拿这三个数去算，不能靠反解字符串",
    )
    status: str = Field(
        description="这一帧的**状态行**：由 scene + overlay 机械拼出来的一句话"
        "（`你在野外。对话框：「…」`）。**不是画面描述**——画面描述是视觉模型写的"
        "`facts[\"overview\"]`，那才是这一帧真正被看到的东西。"
        "这一句只是 prompt 里「当前状态」那一行的内容",
    )
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="结构化状态字段（位置、HP、持有道具…）。机制一的 state key 未来从这里派生",
    )
    done: bool = Field(default=False, description="episode 是否已终止（成功、失败或超步数）")
    success: bool = Field(
        default=False,
        description="任务是否达成。**只在 done 为 True 时有意义**，否则恒为 False",
    )


class PerceptionResult(BaseModel):
    """一次感知动作（`perceive`/`reset`）的结果：观测 + 这次调用产生的模型调用记录。

    `calls` 不放进 `Observation`，因为 `Observation` 是**大脑看的东西**，
    大脑不该知道 token 数、延迟这类记账信息，加进去就是把跨层契约当日志用。
    但这份记账又必须原样传到 Harness 手里去写 trace，所以让它跟 `Observation`
    平行地挂在这一层薄包装上。

    ## 这里曾经有一个 `drain_calls()`

    产生调用记录的地方（世界内部按帧缓存的那个私有方法）被 `reset`/`perceive`
    这些公开方法共用，而它们的返回类型过去只有裸的 `Observation`，装不下 `calls`。于是早一版把调用记录攒进一个实例变量
    （`_pending_calls`），另开一个 `drain_calls()` 方法给 Harness 单独来取。

    这种"生产和消费分离，靠可变状态搭桥"的做法本身就是踩过坑的根源——
    "什么时候清空缓冲区"这件事无论清早了还是清晚了都会把账算错（细看过依赖
    `_pending_calls` 的旧版本能找到完整的事故描述）。真正的修法不是把
    `drain_calls()` 挪个地方，而是让产生调用记录的地方**直接把它当返回值交出来**，
    一路跟着 `_perceive()` → `observe()` → `reset()`/`perceive()`
    普通地往上传——不需要缓冲区，也就不存在"漏记一次账"或"记重一次账"这类
    依赖时机的 bug。

    `calls` 为空列表表示这次调用命中缓存，没有产生新的模型调用——
    **不是 None**，调用方不用先判空值。

    ## 这里没有帧哈希

    曾经有过（`ToolPort` 上一个 property，后来短暂地成为本类的一个字段），
    它的用途是按帧缓存感知结果、以及在 trace 里标出"这条观测是哪一帧"。
    两者都随"**一帧只感知一次**"这条结构约束一起消失了：同一帧不会被问第二遍，
    就没有要缓存的东西，也就不需要一个标记去判断两次观测是不是同一帧。
    详见 `tools/SPEC.md` 2.7。
    """

    observation: Observation
    calls: list[dict[str, str]] = Field(
        default_factory=list,
        description="这次调用（可能是重试了好几次）产生的每一条模型调用记录，"
        "按发生顺序排列。每条至少含 input_tokens/output_tokens/latency_ms/"
        "attempt/ok，建议一并给 raw（模型原始输出）。**失败的调用也在里面**——"
        "它们同样烧了 token",
    )


# =====================================================================
#  以下不跨层 —— 一帧画面被解析成什么。由 `PyBoyWorld` 产出并就地转成
#  `Observation.facts` 里的字符串，一次都不出现在 `interfaces/` 的签名里。
#  大脑看的是上面的 `Observation`。
# =====================================================================

class Scene(str, Enum):
    """你在什么场合。决定**要读哪些字段**。"""

    FIELD = "field"          # 野外：城镇、路线，可自由走动
    INDOOR = "indoor"        # 室内：研究所、民宅、道馆内部
    BATTLE = "battle"        # 战斗中
    MENU = "menu"            # 系统菜单：START 菜单 / 背包 / 精灵列表 / 状态页
    SHOP = "shop"            # 商店买卖界面
    TRANSITION = "transition"  # 过场：黑屏、进出门、白闪


class Overlay(str, Enum):
    """屏幕上盖着什么等你操作。决定**可以按什么键**。"""

    NONE = "none"      # 没有弹出层，直接操作角色
    DIALOG = "dialog"  # 对话框：一段文本等你推进
    CHOICE = "choice"  # 选择框：一组选项 + 光标


# ---- 两张表：二元组的收益就兑现在这里 ----

OVERLAY_ACTIONS: dict[Overlay, tuple[str, ...]] = {
    Overlay.NONE: ("up", "down", "left", "right", "a", "start"),
    Overlay.DIALOG: ("a",),                      # 方向键无效，只能推进
    # 左右**必须在**：`choice` 底下盖着两种物理布局——商店/对话的 yes-no 是竖排，
    # 战斗行动菜单是 2×2（FIGHT PKMN / ITEM RUN）。曾经这里只有 up/down，
    # 取的是两者的交集，后果是 `RUN` 和 `PKMN` **物理上够不着**：
    # `battle_run_attempt` 这个任务定义了却永远不可能成功。
    # 而大脑不会因此停下——实测它拿"right 不在动作空间"当证据，反推出
    # 「这个菜单其实是线性焦点导航」，然后按 down×3 停在 ITEM 上宣布到达 RUN。
    # **给不出正确的键，换来的不是它不动，是它编一个能解释掩码的世界模型。**
    #
    # 代价是竖排选择框里左右成了空按键：按下去画面不变，白费一步。
    # 这个代价可见（记忆里前后两份快照摆在一起，字段一模一样），
    # 而够不着的选项不可见——只会表现为某个任务成功率恒为 0。
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

SCENE_FIELDS: dict[Scene, tuple[str, ...]] = {
    # 野外与室内**没有 fields**：地形来自模拟器内存（`world/ram.py`），
    # 语义来自 `overview` 和 `landmarks`。
    #
    # 曾经这里是 `facing, north, south, east, west, landmarks`，实测全是噪声：
    # `north: grass ×3` 在主角连走六步的过程中一字未变——它根本不是位置的函数，
    # 是"这张图上半部分是草"的函数。字段名承诺的是**测量**，VLM 交付的是**描述**，
    # 两者差一个数量级，不是把 prompt 写好就能弥合的。
    #
    # `facing` 更不该问模型：朝向就是最后一次按的方向键，world 自己知道，
    # 是确定的量，问模型等于把一个已知量换成一个 8/8 全错的猜测。
    Scene.FIELD: (),
    Scene.INDOOR: (),
    Scene.BATTLE: ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp"),
    # `my_hp` 是 `当前/最大` 数字（我方状态框右下角有数字 HP）；
    # `foe_hp` 没有数字可抄——对手状态框原版就只有一条血条，没有 `当前/最大`
    # 这种数字，所以 `foe_hp` 填的是血条挡位，不是分数。
    # **五档是有序的、封闭的**：满 > 较高 > 过半 > 较低 > 危险，只能是这五个词——
    # `catch_weaken_target` 的判据是"挡位比历史里那几步低"，比大小的前提是
    # 取值落在同一个有序集合里；多一个近义词，那条判据就没法机械核对。
    # 怎么按血条长度分这五档（四等分槽、分界线上往高了取、不要用颜色——画面是黑白的），
    # 见 `prompts/perceive_screen.md` 第二节「五个挡位怎么分」。
    Scene.MENU: ("title",),
    Scene.SHOP: ("money", "items"),
    Scene.TRANSITION: (),
}
"""每个场合期望读到哪些字段。

**这是数据不是类型**：给某个 scene 加一个字段，不改变任何枚举值，
所以不触发 append-only 的约束。字段名进 prompt 告诉 VLM 该填什么，
填出来的值进 `ScreenState.fields`。
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
WALKABLE, BLOCKED = ".", "#"

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


class TerrainMap(BaseModel):
    """从模拟器内存读出的通行图。**不是识别出来的。**

    它抄的是游戏自己的碰撞判定（`CheckTilePassable`）：取目标格的 tile id，
    在 tileset 的可通行表里查找。没有阈值、没有概率、没有识别——
    几何这一维因此是 100% 而不是 87%。

    **它不是 `Observation`**：`Observation` 是大脑看到的东西，这个是感知层的中间物，
    由 `PyBoyWorld` 转成 `Observation.facts` 里的一段文本。
    """

    cells: list[str] = Field(
        description=f"{GRID_ROWS} 行、每行 {GRID_COLS} 个字符，取自 {sorted(MAP_CHARS)}"
    )
    map_id: int = Field(description="当前地图编号（wCurMap）")
    player_x: int = Field(description="主角在地图里的 X 格坐标（wXCoord）")
    player_y: int = Field(description="主角在地图里的 Y 格坐标（wYCoord）")
    facing: str = Field(
        default="",
        description="主角面朝哪边（north/south/west/east），**读自精灵表**（见 `ram.read_facing`）。"
        "空串表示这一格内存读出来不是四个已知值之一",
    )
    ambiguous_cells: int = Field(
        default=0,
        description="有多少格子的四个 8x8 子 tile 通行性不一致。"
        "**这是采样规则的健康指标**：实测 90 格里只有 1 格（门）不一致，"
        "取左下子格后与画面吻合。这个数涨起来就说明采样规则不够用了",
    )

    @field_validator("cells")
    @classmethod
    def _check_shape(cls, v: list[str]) -> list[str]:
        """形状不对就打回。内存读出来的东西形状不对，说明地址或换算错了，
        补齐只会把一个地址 bug 伪装成一张残缺的地图。

        校验地形图的形状，不对就当场打回。
        """
        if len(v) != GRID_ROWS:
            raise ValueError(f"terrain must have {GRID_ROWS} rows, got {len(v)}")
        for i, row in enumerate(v):
            if len(row) != GRID_COLS:
                raise ValueError(f"row {i} has {len(row)} cells, expected {GRID_COLS}")
            bad = set(row) - MAP_CHARS
            if bad:
                raise ValueError(f"row {i} has illegal characters {sorted(bad)}")
        return v

    def at(self, col: int, row: int) -> str:
        """取这一格的地形字符。"""
        return self.cells[row][col]

    def neighbors(self) -> dict[str, str]:
        """四个方向键各自通往的那一格是什么。

        单独给一个方法，因为这四格和其余 86 格不是一回事：它们决定这一步能不能动。

        给出四个方向键各自通往的那一格。
        """
        col, row = PLAYER_CELL
        return {
            "up": self.at(col, row - 1), "down": self.at(col, row + 1),
            "left": self.at(col - 1, row), "right": self.at(col + 1, row),
        }

    def render(self) -> str:
        """渲染成带行列号的文本。**行列号就是全局坐标。**

        ## 为什么不是 0-9

        原来列号是 `0123456789`、行号 `0..8`，那是**屏幕格**：主角恒在 `(4,4)`，
        地图跟着他滚动。于是同一张图上有两套坐标——这里是屏幕格，
        `where` / `landmarks` / `known_objects` 是全局坐标——中间隔着一次换算。

        那次换算是全项目最大的一个错误来源，而且是**我们自己造出来的**：

        - 决策模型每步花一千多个输出 token 反复核对同一行字符，
          还是会得出"(6,4) 是 `#` 所以不可达"，而那一格明明是 `G`。
        - 它把换算结果写进子目标（"移动到屏幕格(7,4)"），
          而那种判据**永远不可能成立**——走过去之后他还是 `(4,4)`。
        - 判定器拿到那句判据，只能把全局的 `x=16 y=2` 读成屏幕的 `(16,2)`。

        把换算删掉，这三类错一起消失。**图上的每个数字和记忆里的每个数字
        现在是同一套东西**，不需要任何转换就能对上。

        ## 没有列号，这是故意的

        行号能横着写（一行一个数，写在左边），列号不能——全局 x 是两三位数，
        而一列只有一个字符宽。试过把列号竖着摞成两行（十位一行、个位一行），
        **模型读不动**：那要求它对着某一列纵向拼数字，比原来的换算还难。

        所以这里干脆不给列号，只在开头写一句这一屏覆盖到哪。

        那一句原来是「这一屏：x 从 2 到 11，y 从 1 到 9」。两个「从…到…」并排，
        读的人得自己认出哪个数配哪一边，而 y 的范围其实**每行开头都写着**，
        重复一遍只是把注意力从真正缺失的那一维（列号）上引开。现在写成
        「最左一列 x=2，最右一列 x=11」——直接说这个数是哪一列的，
        不需要再从一个区间里反推。行列数一并写出来而不是留在 prompt 的手写文字里，
        是因为改了网格尺寸那个数就会漂。
        代价是它没法在图上直接读出某一列的 x——**而这个代价是零**，
        因为它本来就不该在图上数格子找东西：门、招牌、人的确切坐标
        `landmarks` 和 `known_objects` 里已经写好了，四邻 `neighbors` 也已经算好了。
        这张图剩下的用处是**看形状**：往那个方向走得通吗、哪边是死路。
        看形状不需要列号。

        ## 格子之间不加空格

        曾经用 `" ".join(...)` 排得整齐些，实测模型把那些空格也当成了格子——
        一行 10 格看成 19 格，坐标全线错位。
        """
        col, row = PLAYER_CELL
        ys = [self.player_y + r - row for r in range(GRID_ROWS)]
        left, right = self.player_x - col, self.player_x + GRID_COLS - 1 - col
        gutter = max(len(str(y)) for y in ys)

        lines = [
            f"这一屏 {GRID_COLS} 列 × {GRID_ROWS} 行："
            f"最左一列 x={left}，最右一列 x={right}；"
            f"每行开头的 y= 就是那一行的 y（最上 y={ys[0]}，最下 y={ys[-1]}）"
        ]
        for r, line in enumerate(self.cells):
            chars = list(line)
            if r == row:
                chars[col] = PLAYER_MARK
            lines.append(f"y={ys[r]:<{gutter}} " + "".join(chars))
        return "\n".join(lines)

    def landmarks(self) -> list[Landmark]:
        """屏幕上的门 / 招牌 / 人，**换算成全局坐标**。返回 `(类型, x, y)`。

        ## 为什么是全局坐标

        地标是**地图上的一个地点**，它跨步骤存在，所以它的坐标也必须跨步骤成立。
        用屏幕格写的话，走一步同一个 `(7,7)` 指的就是另一块地方了——
        而我们还把它存进了记忆、下一步又喂回去。

        实测代价：模型取回上一步的记忆「民宅的门 (7,7)」，对照当前地图发现
        `(7,7)` 是 `#`，于是花了 **2235 个 output token、49 秒**反复重数那一行字符串，
        试图搞清楚是记忆错了还是地图错了。**两边都没错，是我们给的数据自相矛盾**——
        `MAP_HINT` 里明明白白写着屏幕格"不能跨步骤引用"，然后我们自己跨了。

        换算是纯算术：`全局 = 主角全局坐标 + (屏幕格 - PLAYER_CELL)`，不读新的内存。

        ## 为什么没有名字

        名字（这是谁家、招牌上写什么）在总览画面里**没有可观测的证据**：
        招牌的文字根本没渲染，要按 A 弹对话框才有；所有的门都是同一个深色矩形。
        所以名字只有三个可能来源——

        - **内存**：warp 表里就带着目标地图编号，精确。但那是"世界怎么连起来"，
          正是长程记忆要学的东西，白送等于把这个项目要证明的事删掉。
        - **视觉模型**：三轮实测全在编。真新镇既没有宝可梦中心也没有商店，
          它照样给出了「写着「POKéMON CENTER」的招牌」——那是先验，不是观察。
        - **经验**：走进去看见了什么，然后记住。**只有这一个是对的**，而它是
          语义记忆（object）要做的事。

        所以现在只给类型和位置。语义记忆把"进过 x=13 y=5 那扇门，里面是小茂家"
        沉淀下来之后，名字才会从那边长出来。

        把屏幕上的门/招牌/人换算成全局坐标。
        """
        pc, pr = PLAYER_CELL
        kind = {DOOR: "门", SIGN: "招牌", PERSON: "人"}
        here = self.place()
        return [
            Landmark(
                kind=kind[ch],
                place=Place(map_id=here.map_id,
                            x=here.x + (c - pc), y=here.y + (r - pr)),
            )
            for r, line in enumerate(self.cells)
            for c, ch in enumerate(line)
            if ch in (DOOR, SIGN, PERSON)
        ]

    def place(self) -> Place:
        """主角所在的格子。"""
        return Place(map_id=self.map_id, x=self.player_x, y=self.player_y)

    def render_neighbors(self) -> str:
        """四邻渲染成一行。**相对『我』的方向，不依赖屏幕原点，所以能进记忆。**"""
        n = self.neighbors()
        名 = {"up": "北", "down": "南", "left": "西", "right": "东"}
        return " ".join(f"{名[d]} {n[d]}" for d in ("up", "down", "left", "right"))

    def render_landmarks(self) -> str:
        """渲染成 facts 里那一行。**全局坐标写成 `x= y=`**，和屏幕格的括号写法分开。"""
        return "; ".join(m.render() for m in self.landmarks())


NEEDS_OVERVIEW = (Scene.FIELD, Scene.INDOOR)
"""哪些场合必须给 `overview`。

只有这两个：它们是**有布局可言**的画面，而 `overview` 的作用正是在挑细节之前
先做一次全局判断，给后面的局部判断上约束。

战斗、菜单、商店的内容全在 `fields` 和 `options` 里，那里的 `overview` 是装饰；
把它也设成必填，只会给一堆和它无关的代码添噪声，而契约里的每一条约束
都应该是有人真的依赖的。
"""


CURSOR_MARKS: frozenset[str] = frozenset("\u25b6\u25ba\u25b8\u27a4>")
"""能当光标的那几个字符：`▶` `►` `▸` `➤` `>`。

只收形状对的，不做模糊匹配——模型在不同帧里写过其中好几个，
为一个字符的差异丢掉整帧读数不划算；但也不能把任意字符都当光标，
否则选项本身以标点开头就会被误判成"被选中"。
"""


class ScreenState(BaseModel):
    """一帧画面被解析成的结构化状态。

    字段值统一放 `fields` 这个扁平 dict，而不是给每个 scene 定一个子模型：
    机制三的 state key 要从 `(scene, overlay, fields)` 均匀派生，
    分成多个子模型会让 key 的构造对 scene 分支，得不偿失。
    """

    scene: Scene
    overlay: Overlay

    overview: str = Field(
        default="",
        description="一句话描述整幅画面的布局，例如「左下角一栋房子，上方一片草丛，"
        "中间横着一排断崖」。**必须写在 landmarks 之前**——字段的声明顺序就是模型的"
        "输出顺序，先说整体会约束后面挑地标的结果；反过来先挑地标再总结，"
        "总结就只是在复述已经挑错的东西",
    )

    dialog_text: str = Field(
        default="", description="overlay=DIALOG 时框里的文字；其他情况为空"
    )
    options: list[str] = Field(
        default_factory=list,
        description="overlay=CHOICE 时的选项列表。**菜单的区别在这里，不在类型上**。"
        "给了 `option_lines` 时由它派生，视觉模型不必单独再抄一遍",
    )
    option_lines: list[str] = Field(
        default_factory=list,
        description="选项框逐行照抄，**含最左边那个字符**：有光标写 `▶`，没有写空格"
        "（`[\"▶TACKLE\", \" GROWL\"]`）。`options` 和 `cursor` 都从它派生。"
        "\n\n"
        "**为什么绕这一道：把判断换成转写。** 直接问「光标在哪一项」，"
        "模型要先找到三角、再把它和某个词配对、再说出那个词——是定位加归属判断，"
        "实测经常配错，而配错和配对在输出上一模一样。逐行照抄只要求它回答"
        "「这一行开头有没有三角」，是个局部问题，而三角和选项文字本来就挨着。"
        "\n\n"
        "还白捡两样东西：`options` 不会再被凑成四项（抄几行是几行），"
        "以及**零行或多行带三角时可以判定读错**（见 `_derive_cursor_from_lines`）——"
        "现在读错至少有一半会变成「读不出」，而不是变成一个错的词",
    )
    cursor: str | None = Field(
        default=None,
        description="光标指向那一项的原文（`\"RUN\"`）；未知为 None。"
        "**给了 `option_lines` 时这个字段由派生结果覆盖**，模型自己填的那份只留作对照"
        "（`cursor_said`）——两者不一致的比例就是这个改动值不值得的证据。"
        "**不是序号。** 要序号就得让视觉模型数数，而数数正是它最不擅长的一件事——"
        "`facing` 当初从'问模型'改成读内存，就是因为 8/8 全错。抄一个词它只需做一次"
        "视觉配对，不需要计数。而且这样是**可校验的**：不在 `options` 里就是读错了，"
        "当场作废（见 `_cursor_must_be_one_of_the_options`）；填个 `2` 你没有任何办法"
        "知道它对不对",
    )
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="该 scene 的结构化字段，键取自 SCENE_FIELDS。读不出的字段直接不放，"
        "**不要填占位值**——分不清'没读到'和'读到了空'会污染状态抽象准确率的标定",
    )

    cursor_said: str | None = Field(
        default=None,
        description="模型**自己**说的光标位置，仅在它和派生结果不一致时留下。"
        "不是给大脑读的，是给我们数错误率的——它会随 facts 一起进 trace 和观测台",
    )

    @model_validator(mode="after")
    def _derive_cursor_from_lines(self) -> ScreenState:
        """有 `option_lines` 就用它派生 `options` 和 `cursor`。**派生的赢。**

        恰好一行带光标标记才算数：**零行或两行以上一律 `None`**。这是转写换来的
        自校验——"我没看见三角"和"我看见两个三角"都是明确的读不准信号，
        而在旧契约里它们只会表现为一个看着合法的词。

        标记接受几种常见写法：模型在不同帧里写过 `▶` `►` `>`，形状对就行，
        为一个字符的差异丢掉整帧读数不划算。
        """
        if not self.option_lines:
            return self
        marked = [ln for ln in self.option_lines if ln[:1] in CURSOR_MARKS]
        stripped = [ln[1:].strip() if ln[:1] in CURSOR_MARKS else ln.strip()
                    for ln in self.option_lines]
        derived = marked[0][1:].strip() if len(marked) == 1 else None
        object.__setattr__(self, "options", [x for x in stripped if x])
        if self.cursor != derived:
            object.__setattr__(self, "cursor_said", self.cursor)
        object.__setattr__(self, "cursor", derived)
        return self

    @model_validator(mode="after")
    def _cursor_must_be_one_of_the_options(self) -> ScreenState:
        """光标读出来的词必须是 `options` 里的一项，否则作废成 `None`。

        **这是换成字符串换来的东西**：序号版本没有任何自校验的余地——`cursor=2` 在
        四选项菜单里永远"合法"，读错了也看不出来。词就不一样，对不上就是没读准，
        与其把一个错的词发下去，不如说"不知道"。

        `None` 而不是抛异常：读不出光标是**这一帧的常态**（动画中、光标被挡住），
        不是解析失败。抛异常会让整次感知重跑，代价和收益完全不匹配。
        """
        if self.cursor is not None and self.cursor not in self.options:
            object.__setattr__(self, "cursor", None)
        return self

    @model_validator(mode="after")
    def _overview_comes_with_a_layout(self) -> ScreenState:
        """野外和室内必须给 `overview`。

        它不是补充说明，是**看细节之前的那次全局判断**。允许它缺失，模型就会跳过它
        直接去挑地标——而跳过的正是唯一能牵制那些局部判断的东西。

        校验野外和室内必须给出 overview。
        """
        if self.scene in NEEDS_OVERVIEW and not self.overview.strip():
            raise ValueError(f"scene={self.scene.value} must come with an overview")
        return self

    @field_validator("fields", mode="before")
    @classmethod
    def _stringify(cls, v: object) -> object:
        """把字段值规整成字符串。

        实测：模型会按**语义**给类型——`walkable` 给 `true`（bool），
        `nearby` 给 `["Gramps"]`（list）。它读得完全正确，却因为
        `dict[str, str]` 被整条拒掉。23 帧里有 11 帧栽在这上面，
        而那和感知质量毫无关系。

        判据同 ```json 包裹：**常见格式偏差、语义无歧义，为它判错不划算。**
        `walkable` 是 `true` 还是 `"true"` 是序列化细节。

        为什么不干脆放宽成 `dict[str, Any]`：机制一的 state key 要从 fields 派生，
        值的类型不统一就没法稳定地构造 key。规整在入口做一次，下游永远只见字符串。

        **列表排序后再拼**：模型两次读同一个画面可能给出不同顺序的 `nearby`，
        不排序的话同一个状态会派生出不同的 state key，机制三直接失稳。

        把字段值规整成字符串，容器一律排序。
        """
        if not isinstance(v, dict):
            return v
        out: dict[str, str] = {}
        for k, val in v.items():
            if isinstance(val, bool):
                out[str(k)] = "true" if val else "false"
            elif isinstance(val, (list, tuple, set)):
                out[str(k)] = ", ".join(sorted(str(x) for x in val))
            elif val is None:
                continue  # 读不出的字段直接不放，不留占位值
            else:
                out[str(k)] = str(val)
        return out

    def available_actions(self) -> tuple[str, ...]:
        """当前可按的键。**只由 overlay 决定**，masking 的数据来源。"""
        return OVERLAY_ACTIONS[self.overlay]

    def expected_fields(self) -> tuple[str, ...]:
        """当前 scene 期望读到的字段名。用于组 prompt 和标定完整度。"""
        return SCENE_FIELDS[self.scene]


# ---- 给测试用的自描述 ----
#
# prompt 里的字段清单和输出样例是**手写在 .md 里的**，因为 prompt 文件必须能被
# 完整读到——打开文件看到 `$scene_fields` 的话，"prompt 可 review"就是句空话。
#
# 漂移由**测试**挡：`test_prompts.py` 拿这里的输出和 .md 的内容对照，
# 给某个 scene 加了字段却忘了改 prompt，测试当场失败。
# 防漂移不需要牺牲可读性，两者用不同手段各自解决。


def describe_scene_fields() -> str:
    """把 SCENE_FIELDS 渲染成 prompt 里的字段清单。"""
    lines = []
    for scene, fields in SCENE_FIELDS.items():
        if fields:
            lines.append(f"- `{scene.value}` → {', '.join(f'`{f}`' for f in fields)}")
        else:
            lines.append(f"- `{scene.value}` → 不需要任何字段，`fields` 留空对象")
    return "\n".join(lines)


EXAMPLES: dict[Scene, ScreenState] = {
    Scene.FIELD: ScreenState(
        scene=Scene.FIELD,
        overlay=Overlay.NONE,
        overview="左上角一片草丛，中上方一栋房子、门开在正下方；"
                 "画面中间横着一排断崖，只在主角正下方有个缺口；下半部是空地，左侧立着一块招牌。",
    ),
    Scene.INDOOR: ScreenState(
        scene=Scene.INDOOR,
        overlay=Overlay.DIALOG,
        overview="一间四面是墙的房间，中间一组柜子，柜子前站着一个人；"
                 "右下方有一处出口。画面下方三行被对话框盖住，看不到地面。",
        dialog_text="OAK: Hello there! Welcome to the world of POKéMON!",
    ),
    Scene.BATTLE: ScreenState(
        scene=Scene.BATTLE,
        overlay=Overlay.CHOICE,
        overview="战斗画面：右上是对手，左下是我方背影，右下角是四选项指令框。",
        options=["FIGHT", "PKMN", "ITEM", "RUN"],
        cursor="FIGHT",
        fields={
            "foe_name": "CHARMANDER", "foe_level": "5", "foe_hp": "满",
            "my_name": "AL", "my_level": "5", "my_hp": "19/19",
        },
    ),
    Scene.MENU: ScreenState(
        scene=Scene.MENU,
        overlay=Overlay.CHOICE,
        overview="画面右侧弹出一列主菜单条目，光标停在第二项。",
        options=["POKéDEX", "POKéMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT"],
        cursor="POKéMON",
        fields={"title": "主菜单"},
    ),
    Scene.SHOP: ScreenState(
        scene=Scene.SHOP,
        overlay=Overlay.CHOICE,
        overview="商店买卖界面：上方是所持金钱，下方是商品与价格的列表。",
        options=["POKé BALL", "POTION", "ANTIDOTE", "CANCEL"],
        cursor="POKé BALL",
        fields={"money": "3000", "items": "POKé BALL, POTION, ANTIDOTE"},
    ),
    Scene.TRANSITION: ScreenState(
        scene=Scene.TRANSITION,
        overlay=Overlay.NONE,
        overview="画面正在切换，全黑，没有可辨认的内容。",
    ),
}
"""每个 scene 一份合法样例，**同时是 prompt 的内容基准和测试基准**。

为什么每类都要有：只给一份野外样例时，模型在战斗画面上会照着野外那份的形状填——
把地标也照着编出来。样例是模型唯一能看到的"输出长什么样"的实例，
缺哪一类，那一类就靠它自己猜。

三个样例各自还在示范一件容易错的事：

- `indoor` 带对话框：被挡住的三行**全部写 `?`**，不要凭印象补。
  这是 `?` 唯一一个高频用途，不示范的话模型永远不会用它。
- `battle`：`landmarks` 是空的——战斗画面没有格子坐标可言。
- `transition`：**什么都不填**。过场是一帧没有内容的画面，硬填就是编。

prompt 里的样例是手写的（为了文件可读），本模块的这份是基准，
`test_prompts.py` 逐字对照，漂移当场失败。
"""


def json_output_examples() -> dict[Scene, str]:
    """渲染成 prompt 里那几段 JSON。键是 scene，值是格式化好的 JSON 文本。"""
    return {scene: state.model_dump_json(indent=2) for scene, state in EXAMPLES.items()}


def json_output_example() -> str:
    """野外那一份。保留单数形式是因为它是最主要的一类，测试和文档都常单独引用它。"""
    return json_output_examples()[Scene.FIELD]
