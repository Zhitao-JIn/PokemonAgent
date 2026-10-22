"""大脑在某一步看到的世界（从世界来的观测）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .facts import Facts
from .place_in_world import PlaceInWorld


class Observation(BaseModel):
    """**从世界来的观测**——大脑在某一步看到的世界。

    只放**大脑决策需要的**信息。原始画面、模拟器内部状态不进这里——
    那些属于 harness，大脑看不到也不该看到。
    """

    step: int = Field(
        description="本局累计键数，从 0 开始（局内跨 task 连续不归零）：这一帧是本局"
        "第几个键按下之后的世界状态。world 恒填 0 占位，由 harness 盖章"
        "（task 的 total_acts 快照 + task 内键序）；帧槽 / ActMemory 按它做键。"
        "run 层的局外帧盖全局累计键数（跨局累加——局外帧没有局内语义，0928 定稿）"
    )
    place: PlaceInWorld | None = Field(
        default=None,
        description="主角所在的格子。**结构化的那一份**——"
        "位置仅传结构化原料，文字由prompt模块生成；"
        "而记忆的键要拿这三个数去算，不能靠反解字符串",
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
