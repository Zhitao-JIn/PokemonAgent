"""`read_terrain`（`world/ram.py`）的产出结构——**从内存读出来**的通行图，schema。

原来定义在 `world/ram.py`（"实现文档"）里；这是一份真正的数据契约（`pyboy_world.py`
拼 `Facts` 时要用它，`prompts/decide_action.py` 的手写读图范例也照着它的
`render()` 格式写），"数据形状"和"怎么从内存读出这份数据"分开放，跟
`Facts`/`WorldPort` 是同一个道理，所以搬到这里而不是留在 `ram.py`。

**顶层的 import 只有零依赖的 `Facts`**：`world/interface/__init__.py` 是聚合出口、
包初始化时**立即加载**，所以这一层每个模块的顶层 import 都参与那一次装配；
`domain/` 里被它顶层引用的只有零依赖的 `facts.py`。地形网格的行列数（`GRID_COLS`/
`GRID_ROWS`）与字符表（`MAP_CHARS`）住同包的 `screen_model.py`，只在**方法体内部**
现取——`TerrainMap` 需要它们的地方只有校验那一刻。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from .facts import Facts


class TerrainMap(BaseModel):
    """**从内存读出来**的通行图。**不是识别出来的。**

    它抄的是游戏自己的碰撞判定（`CheckTilePassable`）：取目标格的 tile id，
    在 tileset 的可通行表里查找。没有阈值、没有概率、没有识别——
    几何这一维因此是 100% 而不是 87%。

    **它不是 `Observation`**：观测是大脑看到的东西，这个是感知层的中间物，
    由 `PyBoyWorld` 转成观测 `facts` 里的一段文本。
    """

    cells: list[str] = Field(
        description="9 行、每行 10 个字符，取自地形字符集（完整列表见 "
        "`pokemon_agent.schemas.world.domain.screen_model.MAP_CHARS`）"
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
        from .screen_model import (
            GRID_COLS,
            GRID_ROWS,
            MAP_CHARS,
        )

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
        from .screen_model import PLAYER_CELL

        col, row = PLAYER_CELL
        return {
            "up": self.at(col, row - 1),
            "down": self.at(col, row + 1),
            "left": self.at(col - 1, row),
            "right": self.at(col + 1, row),
        }

    def landmarks(self) -> list[Facts.Landmark]:
        """屏幕上的门 / 招牌 / 人 / 物 / 石，**换算成全局坐标**。返回 `(类型, x, y)`。

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
        所以名字只有三个可能来源（"物"是例外——拾取瞬间弹出的对话文字本身就是
        名字，见 `harness/episode/store/store_object_semantic_memory/rules.py::_pickup_or_still`
        复用的
        `_dialog_or_still`，不需要再等语义记忆去沉淀）——

        - **内存**：warp 表里就带着目标地图编号，精确。但那是"世界怎么连起来"，
          正是长程记忆要学的东西，白送等于把这个项目要证明的事删掉。
        - **视觉模型**：三轮实测全在编。真新镇既没有宝可梦中心也没有商店，
          它照样给出了「写着「POKéMON CENTER」的招牌」——那是先验，不是观察。
        - **经验**：走进去看见了什么，然后记住。**只有这一个是对的**，而它是
          语义记忆（object）要做的事。

        所以现在只给类型和位置。语义记忆把"进过 x=13 y=5 那扇门，里面是小茂家"
        沉淀下来之后，名字才会从那边长出来。

        把屏幕上的门/招牌/人/物/石换算成全局坐标。
        """
        from .screen_model import (
            BOULDER,
            DOOR,
            ITEM,
            PERSON,
            PLAYER_CELL,
            SIGN,
        )

        pc, pr = PLAYER_CELL
        kind = {
            DOOR: Facts.Landmark.KIND_DOOR,
            SIGN: Facts.Landmark.KIND_SIGN,
            PERSON: Facts.Landmark.KIND_PERSON,
            ITEM: Facts.Landmark.KIND_ITEM,
            BOULDER: Facts.Landmark.KIND_BOULDER,
        }
        here = self.place()
        return [
            Facts.Landmark(
                kind=kind[ch],
                map_id=here.map_id,
                x=here.x + (c - pc),
                y=here.y + (r - pr),
            )
            for r, line in enumerate(self.cells)
            for c, ch in enumerate(line)
            if ch in kind
        ]

    def place(self) -> Any:  # noqa: ANN401 —— 返回 PlaceInWorld；标 Any 避免顶层依赖，见模块 docstring
        """主角所在的格子。"""
        from .place_in_world import PlaceInWorld

        return PlaceInWorld(map_id=self.map_id, x=self.player_x, y=self.player_y)
