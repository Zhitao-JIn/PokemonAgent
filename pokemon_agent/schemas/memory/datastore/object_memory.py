"""语义记忆（object）的写入形态：一次按键对一格物体的交互事件。

事件流是**唯一真源**：harness 判定"这次按键发生了什么"后构造事件，memory 只按
局追加落盘（JSONL）与按需过滤返回，不做任何折叠/派生。消费方（prompt 渲染、
"这扇门通向哪"这类问题）都从事件序列现算——`type` 即语义，不存在字符串约定。

**写时定型**：三种事件各自一个类（`dialog`/`warp`/`still`），公共字段在
`ObjectFactEventBase`。消费方按 `type` 分发，不允许按 payload 内容猜语义——
对话正文以什么开头都是正文，不再有"进入新地图"前缀这类约定。

调用方（harness 判定层）保证：

- 同一 `episode_id` 的事件 `step` 单调不减（恢复时先截断，见 ROADMAP 16）；
- `kind` 是能建档的交互类别（门/人/招牌/物/石…），`place` 是**物体格**——
  不是角色站的格子，角色位置在 `actor_place`。

事件一旦落库不可变：修正只能靠新事件（同姿势后写覆盖先读）或恢复时的截断。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from pokemon_agent.schemas.world import PlaceInWorld


class ObjectFactEventBase(BaseModel):
    """三种交互事件的公共字段：什么时候、在哪、对什么、按了什么。

    前置条件（构造方保证）：`episode_id` 非空；同局 `step` 单调不减；
    `place` 是被影响的物体格，`actor_place` 是按键那一刻角色所在的格——
    两者是不同语义的坐标，不互相推导。
    """

    episode_id: str = Field(description="这一局的标识；落盘按局分文件（ep-{id}.jsonl）")
    step: int = Field(ge=0, description="这次交互发生在第几步；截断与'不读未来'的坐标轴")
    run_id: str = Field(
        default="",
        description="这个交互发生在哪个 run——checkpoint 恢复的落盘签名三元组之一"
        "（run_id/episode_id/step），由 Harness 盖章",
    )
    actor_place: PlaceInWorld = Field(description="按键那一刻角色所在的格")
    place: PlaceInWorld = Field(description="被影响的物体格")
    kind: str = Field(description="物体类别（门/人/招牌/物/石…）；建档与渲染抬头用")
    button: str = Field(
        description="按了哪个键（a/up/down/left/right）；不设值域，把关在姿势方法表"
    )


class ObjectDialogEvent(ObjectFactEventBase):
    """按下去弹出了对话——`text` 是按键后那一帧抄到的对话正文。"""

    type: Literal["dialog"] = "dialog"
    text: str = Field(description="对话正文（VLM 抄回的当帧文字，可能只是一句的一部分）")


class ObjectWarpEvent(ObjectFactEventBase):
    """按键后穿过这格进入了另一张地图——`map_id` 是通往的地图号。"""

    type: Literal["warp"] = "warp"
    map_id: int = Field(description="进入的新地图编号")


class ObjectStillEvent(ObjectFactEventBase):
    """按下去什么都没发生（没动、没换图、没出话）。没有额外载荷。"""

    type: Literal["still"] = "still"


ObjectFactEvent = Annotated[
    ObjectDialogEvent | ObjectWarpEvent | ObjectStillEvent,
    Field(discriminator="type"),
]
"""一格物体的一次交互记录。三个子类按 `type` 判别，消费方按类型分发。"""
