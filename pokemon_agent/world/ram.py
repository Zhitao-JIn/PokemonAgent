"""直接读模拟器内存：坐标、地图编号、地形通行图、门与招牌的位置。

**这些是确定的，不会读错。** 视觉模型看得懂"屏幕上有一扇门"，但说不准它在哪一格；
RAM 说得准。所以凡是 RAM 能回答的，都不问模型——省钱是次要的，主要是省掉一整类
读错。两边的分工写在 `pyboy_world.py` 的模块 docstring 里。

代价是**这一层和游戏版本强绑定**：里面每个地址常量都是《宝可梦 红》的。
换版本要重来一遍，而且读错地址不会报错，只会给出一张看起来合理的错地图——
所以这里的函数都尽量做到"读出来的东西自带可核对的结构"（比如地形图的形状固定
10×9，越界的门和招牌静默丢弃而不是画到别处）。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from pokemon_agent.schemas.world import (
    DOOR,
    GRASS,
    GRID_COLS,
    GRID_ROWS,
    MAP_CHARS,
    PERSON,
    PLAYER_CELL,
    PLAYER_MARK,
    SIGN,
    LandmarkInWorld,
    PlaceInWorld,
)

W_TILEMAP = 0xC3A0
"""屏幕上 20x18 个 tile 的 id。

**已经是屏幕坐标**——这是游戏自己维护的"当前画面"缓冲区，不需要处理 SCX/SCY 滚动，
也不会截到滚动中途的半格。用它比读 PPU 的背景层省掉一整类对齐问题。
"""

SCREEN_COLS, SCREEN_ROWS = 20, 18

W_CUR_MAP = 0xD35E
W_Y_COORD, W_X_COORD = 0xD361, 0xD362
W_COLLISION_PTR = 0xD530
W_GRASS_TILE = 0xD535

W_NUM_WARPS = 0xD3AE
"""门的数量，后面跟着 N 条 `(y, x, 目标 warp, 目标地图)`。

**实测确认**：真新镇读出 3 条，目标是 map 37 / 39 / 40 ——
自己家、小茂家、大木研究所，坐标也和画面对得上。
"""

W_NUM_SIGNS = 0xD4B0
"""招牌的数量，后面跟着 N 条 `(y, x)`。

**实测确认**：真新镇读出 4 条，其中 `(y=5, x=11)` 换算到屏幕正是画面里那块招牌。
"""

W_SPRITES = 0xC100
SPRITE_STRIDE = 16
"""精灵表。每个精灵 16 字节，我们只用四个偏移：

    +0  图片 id（0 = 这个槽位空着）
    +4  屏幕 y 像素
    +6  屏幕 x 像素
    +9  朝向（0 下 / 4 上 / 8 左 / C 右）

0 号槽位是**主角自己**。实测他的 `(x=64, y=60)` 换算过来正好是格子 (4,4)——
y 差的那 4 像素是贴图偏移，这也顺带验证了换算公式。
"""

FACING_BY_BYTE: dict[int, str] = {0: "south", 4: "north", 8: "west", 12: "east"}
"""精灵表 +9 那个字节 → 朝向。取值和 `BUTTON_FACING` 的是同一套词，
因为工具层要拿"这一步按的方向"和"现在面朝的方向"直接比。
"""


def read_facing(mem: Memory) -> str:
    """主角面朝哪边。**读的是游戏自己的状态，不是从我们按过的键推的。**

    不用按键推的理由：开局和过场之后朝向未知（没按过键），而且朝向不进存档，
    checkpoint 恢复不回来——`docs/spec/harness/SPEC.md` 1.4 记着这个洞。

    后置条件：返回 `BUTTON_FACING` 的四个值之一，或空串（读到的不是已知值）。

    读出主角当前朝向。
    """
    return FACING_BY_BYTE.get(int(mem[W_SPRITES + 9]), "")


SUB_TILE = (0, 1)
"""一个 16x16 格子里，拿哪个 8x8 子 tile 去查通行表。`(dc, dr)` = 左下。

**这是实测定出来的，不是猜的。** 90 个格子里只有一个四子格意见不一致——
右边那栋房子的门：左上 `0x0B`、右上 `0x0C`、右下 `0x1C` 都不可通行，
只有左下 `0x1B` 可通行。取左下，门就是能进的，与画面一致。

这也符合直觉：碰撞判的是**脚下那一格**，而角色贴图的脚在格子下半部。
样本只有一个歧义格，所以这条是"当前证据支持"，不是"已证明"——
真正的判据是 `_ambiguous`：它数出还有多少格子存在歧义，一旦这个数涨起来，
就说明这条采样规则不够用了，得回去看游戏是怎么算的。
"""


class Memory(Protocol):
    """只要能按地址取字节就行。

    定义成 Protocol 而不是直接标 `PyBoy`：这个模块**不需要知道模拟器是谁**，
    也就不需要为了测它去起一个真模拟器。
    """

    def __getitem__(self, addr: int | slice) -> int | list[int]:
        """按地址或切片读原始字节。"""
        ...


def read_passable(mem: Memory) -> set[int]:
    """当前 tileset 的可通行 tile 集合。

    后置条件：非空。空集合意味着满屏都走不了，那只可能是读错了地址，
        不可能是游戏的真实状态。

    **表在 bank 0，不在 `wTilesetBank`。** 指针落在 0x0000-0x3FFF，也就是常驻的
    home bank；`wTilesetBank` 管的是 blocks/gfx 数据。游戏自己也没为它切 bank
    （`CheckTilePassable` 直接 `ld a, [hli]`）。
    我第一版照着 `wTilesetBank` 读，得到的是别的数据段的两个字节——
    **不报错，只是安静地给了一张错的表，然后整屏都变成"不可通行"**。

    取当前 tileset 里可以走的 tile 编号。
    """
    lo, hi = mem[W_COLLISION_PTR], mem[W_COLLISION_PTR + 1]
    addr = (hi << 8) | lo

    out: set[int] = set()
    for i in range(256):  # 上限只是防呆；真实的表只有几十项
        b = mem[addr + i]
        if b == 0xFF:
            break
        out.add(int(b))

    assert out, f"collision list at 0x{addr:04X} is empty — wrong address, not a real state"
    return out


def read_screen_tiles(mem: Memory) -> list[list[int]]:
    """屏幕上 20x18 个 tile 的 id。

    取屏幕上 20×18 个 tile 的 id。
    """
    raw = mem[W_TILEMAP : W_TILEMAP + SCREEN_COLS * SCREEN_ROWS]
    return [list(raw[r * SCREEN_COLS : (r + 1) * SCREEN_COLS]) for r in range(SCREEN_ROWS)]


def _entries(mem: Memory, addr: int, stride: int, limit: int = 16) -> list[list[int]]:
    """读一张"先一个数量、再 N 条定长记录"的表。红版的 warp / sign 都是这个形状。

    读一张「先一个数量、再 N 条定长记录」的表。
    """
    n = min(int(mem[addr]), limit)
    return [[int(mem[addr + 1 + i * stride + k]) for k in range(stride)] for i in range(n)]


def read_terrain(mem: Memory) -> TerrainMapFromRam:
    """读出 10x9 的地形图、主角坐标、地图编号。

    后置条件：`cells` 是 GRID_ROWS 行、每行 GRID_COLS 个字符；主角那格标 `@`。

    ## 语义符号也来自内存，不是认出来的

    通行性只说得出"过不去"，说不出那是墙、是门、是招牌还是人——而后面这些
    红版全都存成了结构化的表：门在 warp 表里（还带着通往哪张地图），
    招牌在 sign 表里，人在精灵表里，草丛的 tile id 写在 tileset 头里。

    所以这里读出来的每一个符号都是**精确**的。视觉模型三轮都读错的东西
    （墙认成门、窗户认成人），在这里根本不存在"认"这个动作。

    读出 10×9 的地形图、主角坐标和地图编号。
    """
    passable = read_passable(mem)
    tiles = read_screen_tiles(mem)
    grass = int(mem[W_GRASS_TILE])
    dc, dr = SUB_TILE

    rows: list[list[str]] = []
    ambiguous = 0
    for r in range(GRID_ROWS):
        line: list[str] = []
        for c in range(GRID_COLS):
            quad = [tiles[2 * r + y][2 * c + x] for y in (0, 1) for x in (0, 1)]
            if len({t in passable for t in quad}) > 1:
                ambiguous += 1
            tile = tiles[2 * r + dr][2 * c + dc]
            if tile == grass:
                line.append(GRASS)
            else:
                line.append("." if tile in passable else "#")
        rows.append(line)

    px, py = int(mem[W_X_COORD]), int(mem[W_Y_COORD])
    pc, pr = PLAYER_CELL

    def place(map_x: int, map_y: int, ch: str) -> None:
        """把地图坐标画到屏幕格子上。**越界的静默丢弃**——地图上的门和招牌
        大多在屏幕外，那不是错误，只是这一帧看不到。

        把地图坐标画到屏幕格子上，越界的丢弃。
        """
        c, r = pc + (map_x - px), pr + (map_y - py)
        if 0 <= c < GRID_COLS and 0 <= r < GRID_ROWS:
            rows[r][c] = ch

    # 顺序 = 优先级，后写的盖前面的：招牌 < 门 < 人。
    # 人放最后是因为他会站在门口——那时候"这里有个人"比"这里有扇门"更要紧，
    # 你得先跟他说话或者绕开，门在他身后没有意义。
    for y, x in [(e[0], e[1]) for e in _entries(mem, W_NUM_SIGNS, 2)]:
        place(x, y, SIGN)
    for y, x in [(e[0], e[1]) for e in _entries(mem, W_NUM_WARPS, 4)]:
        place(x, y, DOOR)
    for i in range(1, 16):  # 0 号是主角自己，跳过
        base = W_SPRITES + i * SPRITE_STRIDE
        if int(mem[base]) == 0:
            continue
        sx, sy = int(mem[base + 6]), int(mem[base + 4])
        c, r = sx // 16, (sy + 4) // 16
        if 0 <= c < GRID_COLS and 0 <= r < GRID_ROWS:
            rows[r][c] = PERSON

    return TerrainMapFromRam(
        cells=["".join(row) for row in rows],
        map_id=int(mem[W_CUR_MAP]),
        player_x=px,
        player_y=py,
        facing=read_facing(mem),
        ambiguous_cells=ambiguous,
    )


# ---- `read_terrain` 的产出结构（原 schemas/domain，因只被 world 内部消费而降级于此）----


class TerrainMapFromRam(BaseModel):
    """**从内存读出来**的通行图。**不是识别出来的。**

    它抄的是游戏自己的碰撞判定（`CheckTilePassable`）：取目标格的 tile id，
    在 tileset 的可通行表里查找。没有阈值、没有概率、没有识别——
    几何这一维因此是 100% 而不是 87%。

    **它不是 `ObservationFromWorld`**：观测是大脑看到的东西，这个是感知层的中间物，
    由 `PyBoyWorld` 转成观测 `facts` 里的一段文本。
    """

    cells: list[str] = Field(
        description=f"{GRID_ROWS} 行、每行 {GRID_COLS} 个字符，取自 {sorted(MAP_CHARS)}"
    )
    map_id: int = Field(description="当前地图编号（wCurMap）")
    player_x: int = Field(description="主角在地图里的 X 格坐标（wXCoord）")
    player_y: int = Field(description="主角在地图里的 Y 格坐标（wYCoord）")
    facing: str = Field(
        default="",
        description="主角面朝哪边（north/south/west/east），**读自精灵表**（见 `read_facing`）。"
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
            "up": self.at(col, row - 1),
            "down": self.at(col, row + 1),
            "left": self.at(col - 1, row),
            "right": self.at(col + 1, row),
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

        ## 没有逐格列号，行尾给范围

        行号能横着写（一行一个数，写在左边），逐格列号不能——全局 x 是两三位数，
        而一列只有一个字符宽。试过把列号竖着摞成两行（十位一行、个位一行），
        **模型读不动**：那要求它对着某一列纵向拼数字，比原来的换算还难。

        但「只在开头写一句这一屏覆盖到哪」实测也不够：行起点随相机滚动每帧都变，
        模型要做「行起点 x + 字符索引」的换算，且会把手写说明里的示例坐标声明
        （`decide_action.py` 的 `_sample_map`）当成通用规则套用到当前帧上，
        算出矛盾后开始长篇自我核对（2026-09-08 实测一条 thought 烧掉 1633
        output token，详见 `CHANGELOG.md`）。所以现在改成**每一行行尾直接标注
        该行的全局 x 范围**——不是逐格列号（那还是读不动），是把「起点+索引」
        的换算降为一次查表；开头一句只解释括号的含义，不再重复具体数字，
        避免同一信息出现两份。

        ## 格子之间不加空格

        警示：空格会被模型当成格子——一行 10 格看成 19 格，坐标全线错位。
        行尾的 `(x=..)` 括号是标注不是格子，图例里没有 `(` 和 `)` 这两种字符。
        """
        col, row = PLAYER_CELL
        ys = [self.player_y + r - row for r in range(GRID_ROWS)]
        left, right = self.player_x - col, self.player_x + GRID_COLS - 1 - col
        gutter = max(len(str(y)) for y in ys)

        lines = [f"这一屏 {GRID_COLS} 列 × {GRID_ROWS} 行；每行末尾括号里是该行首尾两格的全局 x"]
        for r, line in enumerate(self.cells):
            chars = list(line)
            if r == row:
                chars[col] = PLAYER_MARK
            lines.append(f"y={ys[r]:<{gutter}} " + "".join(chars) + f"  (x={left}..{right})")
        return "\n".join(lines)

    def landmarks(self) -> list[LandmarkInWorld]:
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
            LandmarkInWorld(
                kind=kind[ch],
                place=PlaceInWorld(map_id=here.map_id, x=here.x + (c - pc), y=here.y + (r - pr)),
            )
            for r, line in enumerate(self.cells)
            for c, ch in enumerate(line)
            if ch in (DOOR, SIGN, PERSON)
        ]

    def place(self) -> PlaceInWorld:
        """主角所在的格子。"""
        return PlaceInWorld(map_id=self.map_id, x=self.player_x, y=self.player_y)

    def render_neighbors(self) -> str:
        """四邻渲染成一行。**相对『我』的方向，不依赖屏幕原点，所以能进记忆。**"""
        n = self.neighbors()
        名 = {"up": "北", "down": "南", "left": "西", "right": "东"}
        return " ".join(f"{名[d]} {n[d]}" for d in ("up", "down", "left", "right"))

    def render_landmarks(self) -> str:
        """渲染成 facts 里那一行。**全局坐标写成 `x= y=`**，和屏幕格的括号写法分开。"""
        return "; ".join(m.render() for m in self.landmarks())
