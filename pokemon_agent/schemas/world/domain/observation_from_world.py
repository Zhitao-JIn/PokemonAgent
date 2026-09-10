"""大脑在某一步看到的世界（从世界来的观测）。"""

from __future__ import annotations

import unicodedata

from pydantic import BaseModel, Field

from .place_in_world import PlaceInWorld


def _display_width(text: str) -> int:
    """这段文字占几个字符宽。**中日韩字符算两格。**

    对齐要用它而不是 `len()`：标签里中英混排（`位置` 和 `my_hp` 同时出现），
    按字数补空格的话，中文那几行会短一半——而这份文本的**唯一用途**就是让大脑
    逐行对照前后两份快照，列对不齐等于把配对的活又推回给它。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


FIELD_ORDER: tuple[str, ...] = (
    "scene",
    "overlay",
    "where",
    "facing",
    "neighbors",
    "landmarks",
    "dialog_text",
    "options",
    "cursor",
    "my_name",
    "my_level",
    "my_hp",
    "foe_name",
    "foe_level",
    "foe_hp",
    "overview",
    "walk_map",
)
"""渲染顺序。`walk_map` 和 `overview` 垫底：一个占九行、一个措辞每次都变，
摆在前面会把真正逐行对照的那几项挤下去。`overview` 更靠前——它是这堆字段里唯一由视觉模型自由措辞的一项，
同一帧能给出三种说法，摆在前面会让大脑先读到噪声最大的那行。"""

FIELD_LABEL: dict[str, str] = {
    "where": "位置",
    "neighbors": "四邻",
    "dialog_text": "对话",
    "overview": "概况",
    "landmarks": "地标",
    "options": "选项",
    "cursor": "光标",
    "scene": "场景",
    "overlay": "叠加层",
    "facing": "朝向",
}
"""字段名 → 中文标签。表外的字段直接用原名，不强行翻译。"""


class ObservationFromWorld(BaseModel):
    """**从世界来的观测**——大脑在某一步看到的世界。

    只放**大脑决策需要的**信息。原始画面、模拟器内部状态不进这里——
    那些属于 harness，大脑看不到也不该看到。
    """

    step: int = Field(description="本 episode 内的第几步，从 0 开始")
    place: PlaceInWorld | None = Field(
        default=None,
        description="主角所在的格子。**结构化的那一份**——"
        '`facts["where"]` 是它渲染出来给模型读的文本，'
        "而记忆的键要拿这三个数去算，不能靠反解字符串",
    )
    status: str = Field(
        description="这一帧的**状态行**：由 scene + overlay 机械拼出来的一句话"
        "（`你在野外。对话框：「…」`）。**不是画面描述**——画面描述是视觉模型写的"
        '`facts["overview"]`，那才是这一帧真正被看到的东西。'
        "这一句只是 prompt 里「当前状态」那一行的内容",
    )
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="结构化状态字段（位置、HP、持有道具…）。机制一的 state key 未来从这里派生",
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

        `dialog_text` **在键里**，是刻意的：长对话逐句推进时，场景/光标/位置
        全都不变，唯一在变的就是对话文本——文本在推进就是有进展，不能判停摆；
        反过来，同一句对话原地重按（键不变）才是真的打转。它是 world 机械
        读出的文本，不是视觉模型的自由措辞，同帧重读稳定。

        刻意**不进键**的字段：`overview`（视觉模型的自由措辞，同一帧重读都会
        变字，进了键停摆永远检测不出来）、`walk_map`（大且由位置派生）、
        记忆检索折进来的 `known_objects`/`knowledge`/`episode_memories`
        （不是这一帧的事实，且随检索结果变）。位置用结构化的 `place.key`，
        不用 `facts["where"]` 那份渲染文本。
        """
        place = self.place.key if self.place is not None else "-"
        return "|".join(
            (
                place,
                self.facts.get("scene", ""),
                self.facts.get("overlay", ""),
                self.facts.get("cursor", ""),
                self.facts.get("dialog_text", ""),
            )
        )

    def render(self, indent: str = "  ") -> str:
        """把这份观测渲染成一段可读、可打分的文本。

        **按 `FIELD_ORDER` 排，表外的字段按名字排在后面。** 顺序固定不是为了好看：
        前后两份观测要摆在一起给大脑比对，同一个字段在两份里必须出现在同一个相对
        位置，否则"哪一项变了"就得靠它先做一次字段配对。
        """
        keys = [k for k in FIELD_ORDER if k in self.facts]
        keys += sorted(k for k in self.facts if k not in FIELD_ORDER)
        if not keys:
            return f"{indent}{self.status}"
        labels = {k: FIELD_LABEL.get(k, k) for k in keys}
        width = max(_display_width(v) for v in labels.values())
        lines = []
        for k in keys:
            pad = " " * (width - _display_width(labels[k]) + 2)
            # **多行的值（`walk_map`）续行要缩进到同一列。** 顶格续行的话，
            # 图的第二行看起来就像下一个字段，而这份文本存在的意义正是让大脑
            # 按列扫过去比对前后两份。
            gutter = " " * (len(indent) + width + 2)
            body = self.facts[k].replace("\n", "\n" + gutter)
            lines.append(f"{indent}{labels[k]}{pad}{body}")
        return "\n".join(lines)
