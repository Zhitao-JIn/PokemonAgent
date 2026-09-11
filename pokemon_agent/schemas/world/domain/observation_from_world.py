"""大脑在某一步看到的世界（从世界来的观测）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .place_in_world import PlaceInWorld

from pokemon_agent.world.interface import Facts

# **`place_in_world` 排在 `world.interface` 前面导入，是刻意的顺序**：
# `Facts`（`world/interface/domain/facts.py`）自己也要 `PlaceInWorld`
# （`Facts.Landmark.place`），如果这个文件先导 `Facts` 再导 `PlaceInWorld`，
# 等 `Facts` 内部去找 `PlaceInWorld` 时，这个模块所在的 `schemas.world` 聚合包
# 可能还没跑到定义它的那一行——先把 `PlaceInWorld` 在这里导完，`Facts` 内部
# 再要同一个类型时命中的是已经缓存好的模块，不会重新触发一次可能踩坑的导入链。


class ObservationFromWorld(BaseModel):
    """**从世界来的观测**——大脑在某一步看到的世界。

    只放**大脑决策需要的**信息。原始画面、模拟器内部状态不进这里——
    那些属于 harness，大脑看不到也不该看到。
    """

    step: int = Field(description="本 episode 内的第几步，从 0 开始")
    place: PlaceInWorld | None = Field(
        default=None,
        description="主角所在的格子。**结构化的那一份**——"
        "`facts.where` 是它渲染出来给模型读的文本，"
        "而记忆的键要拿这三个数去算，不能靠反解字符串",
    )
    status: str = Field(
        description="这一帧的**状态行**：由 scene + overlay 机械拼出来的一句话"
        "（`你在野外。对话框：「…」`）。**不是画面描述**——画面描述是视觉模型写的"
        "`facts.overview`，那才是这一帧真正被看到的东西。"
        "这一句只是 prompt 里「当前状态」那一行的内容",
    )
    facts: Facts = Field(
        default_factory=Facts,
        description="结构化事实容器（场景、叠加层、地标、位置文本、HP……）。"
        "`Facts` 本身是 Pydantic 模型，字段该是什么类型就是什么类型——"
        "结构化的东西（`scene`/`overlay`/`landmarks`）不再被迫先渲染成文本塞进"
        "一个 `dict[str, str]`，判定层/记忆检索也不用再从文本反解回来"
        "（定义见 `pokemon_agent/world/interface/domain/facts.py`）。"
        "机制一的 state key 未来从这里派生",
    )
    done: bool = Field(
        default=False,
        description=(
            "**世界层自己的信号**：这个观测产生时，世界本身是不是已经不在了"
            "（目前唯一来源是模拟器窗口被关闭）。**不是**「这一局该不该结束」——"
            "那是 harness 综合三类机械条件 + judge 判定之后的结论，归 "
            "`EpisodeRunState.done`，不借用/覆写这个字段。这里只读不写：世界层"
            "产出观测时给一次值，之后没有任何人再改它"
        ),
    )

    def stall_key(self) -> str:
        """停摆检测用的**机械状态键**：只含不会因重读而变化的字段。

        L2 护栏（episode 内停摆检测）拿它和上一步的键比——**键相等就是
        "动作和画面都没有产生任何效果"的 equal 判定**。做成"返回键"而不是
        `equal(other)` 方法，是因为键要跨步存进 `EpisodeRunState`（可序列化的
        一个字符串），比较在下一个节点做。

        字段清单与"为什么是这几个"见 `Facts.stall_key_part()`——这里只拼上
        位置那一段（`place.key`，结构化坐标，不用 `facts.where` 那份渲染文本）。
        """
        place = self.place.key if self.place is not None else "-"
        return "|".join((place, self.facts.stall_key_part()))

    def render(self, indent: str = "  ") -> str:
        """把这份观测渲染成一段可读、可打分的文本。

        **字段顺序固定不是为了好看**：前后两份观测要摆在一起给大脑比对，同一个
        字段在两份里必须出现在同一个相对位置，否则"哪一项变了"就得靠它先做一次
        字段配对。具体顺序在 `Facts._entries()` 里维护。
        """
        body = self.facts.render(indent)
        return body if body else f"{indent}{self.status}"
