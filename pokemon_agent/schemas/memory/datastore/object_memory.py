"""语义记忆（object）的写入形态：一次按键对一格物体的交互事件。

事件流是**唯一真源**：harness 判定"这次按键发生了什么"后构造事件，memory 只按
局追加落盘（JSONL）与按需过滤返回，不做任何折叠/派生。消费方（prompt 渲染、
"这扇门通向哪"这类问题）都从事件序列现算——`type` 即语义，不存在字符串约定。

**写时定型**：三种事件各自一个类（`dialog`/`warp`/`still`），公共字段在
`ObjectFactEventBase`。消费方按 `type` 分发，不允许按 payload 内容猜语义——
对话正文以什么开头都是正文，不再有"进入新地图"前缀这类约定。

调用方（harness 判定层）保证：

**两个名字为什么不是 `type` / `kind`**（0914 跟进）：封套上 `type` 是事件粗类、
`kind` 是账名——这两个名字已经是 trace 的保留字。本记录**整份 dump 进
`write_object_memory` 账的正文**，正文键与封套键撞名的话，判据
（`node_io._WRITE_FORBIDDEN_KEYS`）就没法把"记录自己的字段"和"把封套的东西抄进
正文"分开。所以判别键叫 **`outcome`**（这次按键造成了哪种结局：dialog / warp /
still），物体类别叫 **`object_kind`**（那格是什么类别的东西）。

- 同一 `episode_id` 的事件 `step` 单调不减（恢复时先截断，见 ROADMAP 16）；
- `object_kind` 是能建档的交互类别（门/人/招牌/物/石…），`place` 是**物体格**——
  不是角色站的格子，角色位置在 `actor_place`。

事件一旦落库不可变：修正只能靠新事件（同姿势后写覆盖先读）或恢复时的截断。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ObjectFactEventBase(BaseModel):
    """三种交互事件的公共字段：什么时候、在哪、对什么、按了什么。

    **判别键叫 `outcome`**（`dialog`/`warp`/`still`）——它答"这一键造成了哪种
    结局"，与 `ObjectFactEvent` 的三个子类一一对应；不叫 `type`，那是 trace
    封套保留的名字。

    **判别键叫 `outcome`**（`dialog`/`warp`/`still`）——它答"这一键造成了哪种
    结局"，与 `ObjectFactEvent` 的三个子类一一对应；不叫 `type`，那是 trace
    封套保留的名字。

    前置条件（构造方保证）：`episode_id` 非空；同局 `step` 单调不减；
    `place` 是被影响的物体格，`actor_place` 是按键那一刻角色所在的格——
    两者是不同语义的坐标，不互相推导。
    """

    class Place(BaseModel):
        """事件里"格子"的快照——**不是** `pokemon_agent.world.PlaceInWorld`。

        事件一旦落库就不可变，这里只需要 `PlaceInWorld` 的**形状**
        （`map_id`/`x`/`y`），不需要它的行为（`step_toward()` 只有判定层
        `harness/episode/store/store_object_semantic_memory/rules.py` 拿着真身才用得到，
        `render()` 这类
        文案也各自需要各自的措辞）。按"模块间零依赖，只靠裸字段交互"这条
        边界，这里独立声明一份字段一致、类不互相引用的内部类型——
        `harness/episode/store/store_object_semantic_memory/rules.py`（唯一的组装方）负责在构造事件前
        把真身 `PlaceInWorld.model_dump()` 拍平后验证成这里的类型。

        `key` property 照抄真身：语义记忆按 `(map_id, x, y)` 索引，这个键
        跟真身的算法必须一致，`tools/memory_tool.py` 落索引时两边不能算出
        两个不同的字符串。
        """

        map_id: int
        x: int
        y: int

        @property
        def key(self) -> str:
            """记忆的键。**跨 episode 稳定**——同一张地图上的同一格永远是同一个键。"""
            return f"{self.map_id}:{self.x}:{self.y}"

    episode_id: str = Field(description="这一局的标识；落盘按局分文件（ep-{id}.jsonl）")
    step: int = Field(ge=0, description="这次交互发生在第几步；截断与'不读未来'的坐标轴")
    run_id: str = Field(
        default="",
        description="这个交互发生在哪个 run——checkpoint 恢复的落盘签名三元组之一"
        "（run_id/episode_id/step），由 Harness 盖章",
    )
    actor_place: Place = Field(description="按键那一刻角色所在的格")
    place: Place = Field(description="被影响的物体格")
    object_kind: str = Field(description="物体类别（门/人/招牌/物/石…）；建档与渲染抬头用")
    button: str = Field(
        description="按了哪个键（a/up/down/left/right）；不设值域，把关在姿势方法表"
    )


class ObjectDialogEvent(ObjectFactEventBase):
    """按下去弹出了对话——`text` 是按键后那一帧抄到的对话正文。"""

    outcome: Literal["dialog"] = "dialog"
    text: str = Field(description="对话正文（VLM 抄回的当帧文字，可能只是一句的一部分）")


class ObjectWarpEvent(ObjectFactEventBase):
    """按键后穿过这格进入了另一张地图——`map_id` 是通往的地图号。"""

    outcome: Literal["warp"] = "warp"
    map_id: int = Field(description="进入的新地图编号")


class ObjectStillEvent(ObjectFactEventBase):
    """按下去什么都没发生（没动、没换图、没出话）。没有额外载荷。"""

    outcome: Literal["still"] = "still"


ObjectFactEvent = Annotated[
    ObjectDialogEvent | ObjectWarpEvent | ObjectStillEvent,
    Field(discriminator="outcome"),
]
"""一格物体的一次交互记录。三个子类按 `outcome` 判别，消费方按类型分发。"""
