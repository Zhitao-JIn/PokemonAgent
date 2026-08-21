"""语义记忆契约：**世界是什么样，域内恒真。**

现在只有一类语义记忆——**object**：某一格上的东西（门/招牌/人），跟它互动会得到
什么。以后加别的类别（比如"属性克制表"）时，各类别各有自己的事实模型，
不要都往 `ObjectFact` 里塞字段——那会把"这一格给了什么"和"水克火"这种
不挂在坐标上的知识混进同一张表。

这是 `ObjectNote` 改的名字：早先它只是"这次交互记了什么"的一个临时想法，
搬进语义记忆这一层之后它的身份更明确了——**它是语义记忆里"object"这一类事实
的存储形状**，`memory/port.py` 的协议、`memory/semantic/object_store.py` 的实现，
读写的都是这个类型。往后语义记忆还会有更多用途（比如从 `attempts` 里学出
"这一类地形的门都要从北边推"这种跨对象的规律），`ObjectFact` 这个名字留了空间，
`ObjectNote`（"记了一笔"）没有。

**跨层，但只跨这一小段**：从不出现在 `WorldPort`/`GameToolPort` 的签名里，
只出现在 `MemoryToolPort`（见 `interfaces/tools.py`）——大脑不该知道
"语义记忆""ObjectFact"这些词，它看到的只是 `known_objects` 里的一段渲染文字。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .observation import KIND_DOOR, Landmark

RESULT_NONE = "无效果"
RESULT_DIALOG = "对话"
RESULT_WARP_PREFIX = "进入新地图"
"""固定结果集合。**只有这三种**，判"这扇门开没开"就靠是不是
以 `RESULT_WARP_PREFIX` 开头——所以这个前缀只能有一处定义。

早一版门专门区分"没换图"和"没动"，人/招牌区分"没反应"和"没出现文字"——
四种叫法说的其实都是同一件事："这次按键没起作用"。合并成
`RESULT_NONE` 一种，模型不需要再学两套近义词。
"""

MAX_TRIED = 8
"""一个对象最多记几条尝试。

一扇门总共只有 8 种碰法（**站在门上按 4 个方向 + 从 4 个相邻格推 1 个方向 = 8**，
这是坐标几何决定的穷尽上限，不需要再单独列一张词汇表）。
**试过的不淘汰**——超过上限时丢最早的一条，但同一个 `(坐标, 按键)` 再试一次
只会覆盖旧值、不占新名额，所以正常情况下 8 条足够盖住全部碰法。
"""

MAX_OBJECT_LINES = 4
"""一个对象最多记几句话。

有上限不是怕内存，是怕 prompt：这些条目每一帧都要发，而一个 NPC 在剧情推进时
可能说几十句。留最近几句够用了——**要点是"这是谁"，不是复述完整台词**。
"""


class ObjectFact(BaseModel):
    """**语义记忆（object）的存储形状**：某一格上的东西，跟它互动会得到什么。

    ## 为什么它和情景记忆是两种东西

    情景记忆（`MemoryEntry`）记的是「我在那种画面里选了什么、结果如何」——
    作用域是**一次经过**，取回来靠画面相似。

    这一条记的是「**地图39 x=2 y=3 那个人会说什么**」。作用域是那一格本身，
    在那个作用域里**永远为真**，而且那个作用域会反复出现（下一步、下一局、下周）。
    这正是长期记忆的范式：自带作用域 + 域内恒真 + 域会再现。

    ## 它解决的具体问题

    实测：agent 走进小茂家，对着一个 NPC 连按 `a`，自己在 rationale 里写下
    "landmarks 中『人 x=2 y=3』…**确认为母亲**"——那是**凭空断言的身份**。
    这句话进了情景记忆，下一步被取回，它照着自己的断言又按一次，如此循环。

    判定器每一步都在说"这是 'BLUE is out at GrandPa's lab.'，不是母亲说的话"，
    但**判定器的话到不了决策模型手里**（那条隔离是有意的：让被评价者看见评价者的
    理由，它就会开始朝着评价者的措辞优化）。

    有了这条记忆，下一次站在同一格前面，`known_objects` 里直接写着那个人说过什么——
    **不需要再猜，也不需要再按一次才知道**。名字这一维终于有了正当来源。

    ## 「怎么碰它」也是记忆的一部分，而且不按类型分字段

    同一格东西的交互方式不止一种：有的门走上去就换图，有的门要**踩在门格上**
    再朝外按方向才走得掉，坡只有一个方向能跳下去。看着是三类东西，
    拆开只差两维：**我人在它旁边还是站在它上面**、**按的哪个方向**。

    所以不给「门」加 `how`、给「坡」加 `one_way`——那些是**结论**，
    只能靠模型断言或者我写死规则，而这个项目里凡是靠断言进记忆的东西
    最后都会被当成事实反复使用。这里存的是 `attempts`：**姿势 → 结果**，
    两边都由 `place` 相减算出来，可证伪，也不需要预先知道有几种类型。

    ## 通行性归内存，方向性归记忆

    「这一格能不能站」永远不进这里——`walk_map` 每帧从内存现算，
    那是低层控制，不该由长期记忆来猜。但 `walk_map` 只答"能不能站"，
    **答不了方向**：从北边能跳下坡、从南边跳不上来，两次问的是同一格。
    有方向的那一半才是这份档案的活。
    """

    landmark: Landmark

    seen: int = Field(default=0, description="进过几次视野。**一步最多加一次**")
    touched: int = Field(default=0, description="互动过几次（对着它按 a、或走进这扇门）")
    first_seen: str = Field(default="", description="第一次见到的时刻，形如 `ep0#3`")
    last_seen: str = Field(default="", description="最近一次见到的时刻")

    lines: list[str] = Field(
        default_factory=list,
        description="跟它互动时出现过的文本，按第一次出现的顺序，去重。"
        "**同一个 NPC 会说好几句**，所以是列表不是单条",
    )
    attempts: dict[str, str] = Field(
        default_factory=dict,
        description="**`x=.. y=..→按键` → 结果**，记「怎么碰它才有用」。"
        "键就是按键那一刻角色自己的坐标 + 按了哪个键，不翻译成中文姿势——"
        "角色坐标和这个对象的坐标一比就知道是站在上面还是从哪边推。"
        "值只有三种（见 `RESULT_NONE` / `RESULT_DIALOG` / `RESULT_WARP_PREFIX`），"
        "都是算出来的：键来自按键那一刻的 `before.place`，"
        "值来自 `before.place` 和 `after.place` 一减、或 `after` 有没有新对话文字",
    )

    @property
    def leads_to(self) -> int | None:
        """这扇门通往哪张地图；没打开过就是 `None`。

        **不是存下来的字段，是从 `attempts` 里算出来的**——省去了"两处真相"
        （字段和 `attempts` 里的那条 `进入新地图N` 万一对不上）的问题。
        成功是算出来的，不是模型判断的：门 = `map_id` 变了，
        所以直接扫 `attempts` 里第一条以 `RESULT_WARP_PREFIX` 开头的结果。
        """
        for result in self.attempts.values():
            if result.startswith(RESULT_WARP_PREFIX):
                return int(result.removeprefix(RESULT_WARP_PREFIX))
        return None

    def record(self, key_desc: str, result: str) -> None:
        """记下一次尝试的结果。**同一个 `(坐标, 按键)` 以最新的为准。**

        不是"第一次记下就不改"，因为结果真的会变：一扇本来锁着的门后来开了、
        一条本来有人挡着的路后来通了。旧结论留着比没有更糟——
        它会让 agent 反复绕开一条已经通了的路。
        """
        if not key_desc or not result:
            return
        self.attempts.pop(key_desc, None)   # 重新插到末尾，让淘汰按"最近用过"走
        self.attempts[key_desc] = result
        for stale in list(self.attempts)[:-MAX_TRIED]:
            del self.attempts[stale]

    def see(self, line: str) -> None:
        """记下一句。**滚动窗口要拼回一句话，不是当成好几句。**

        GB 的对话框一次只显示两行，按一次 `a` 往上滚一行，视觉模型每帧抄下
        看得见的部分。所以连着几帧抄回来的是**同一句话的四个重叠窗口**：

            MOM: Oh good! You and your
            You and your POKéMON are
            POKéMON are looking great!
            looking great! Take care now!

        早一版只做完全相同去重，于是这四条各占一格、塞满 `MAX_OBJECT_LINES`，
        下一句进来就把 `MOM: Oh good!` 挤掉——**而那是唯一带身份的一句**。
        实测档案里那个 NPC 最后只剩半截话，"这是谁"完全丢了。

        拼接是纯字符串运算：前一条的尾巴和这一条的开头重叠多少，就接在哪。
        不需要模型，也不会引入新的错。
        """
        text = line.strip()
        if not text:
            return
        if self.lines:
            merged = _stitch(self.lines[-1], text)
            if merged is not None:
                self.lines[-1] = merged
                return
        if text not in self.lines:
            self.lines.append(text)
        self._trim()

    def _trim(self) -> None:
        """留够条数，但**第一条永远留着**。

        淘汰最早的那条是照抄滑动窗口的做法，而这里的第一条恰恰最不可替代：
        NPC 的自我介绍、招牌的标题都在开头。后面的台词随剧情推进，
        丢一句无所谓；丢了第一句，这条档案就回答不了"这是谁"了。
        """
        if len(self.lines) > MAX_OBJECT_LINES:
            self.lines[:] = self.lines[:1] + self.lines[-(MAX_OBJECT_LINES - 1):]

    def render(self) -> str:
        """渲染成 `known_objects` 里的一行。

        **"还没互动过"也要写出来。** 这份档案最有价值的一类条目正是它：
        "这里有一扇门，我见过 7 次，一次都没进去过"——那是它自己的待办清单，
        而没有这条信息，它只能靠 `landmarks` 看到那里有扇门，
        分不出哪扇是探索过的、哪扇是新的。

        门用 `leads_to` 单独判过一次——开没开是**唯一要紧的问题**，
        开了就直接写结论，不用把一串尝试流水交给模型自己找哪条是成功。
        没开的话把 `attempts` 原样列出来：键本来就是"坐标→按键"，
        模型自己拿角色当时的位置一比就知道是推门还是站上面按，
        不需要这一层再翻译成"站在南边"这种措辞。
        """
        parts: list[str] = []
        if self.lines:
            parts.append(" / ".join(self.lines))
        if self.landmark.kind == KIND_DOOR:
            if self.leads_to is not None:
                parts.append(f"通往地图{self.leads_to}")
            elif self.attempts:
                tried = "；".join(f"{k}→{v}" for k, v in self.attempts.items())
                rest = f"，还剩 {MAX_TRIED - len(self.attempts)} 种没试" if len(self.attempts) < MAX_TRIED else ""
                parts.append(f"**还没打开过**（试过 {tried}{rest}）")
            else:
                parts.append("**还没打开过**")
        elif self.attempts:
            parts.append("；".join(f"{k}→{v}" for k, v in self.attempts.items()))
        if not parts:
            parts.append("互动过但没出现文字" if self.touched else "**还没互动过**")
        return (
            f"{self.landmark.place.render()} 的「{self.landmark.kind}」"
            f" → {'；'.join(parts)}"
            f"（见过 {self.seen} 次，互动 {self.touched} 次）"
        )


MIN_STITCH = 6
"""拼接至少要重叠几个字符（见 `_stitch`）。取值理由同 `schemas/memory_episodic.py`
的那份——两处各自独立，因为拼接的是两种不同的滚动窗口内容，没有必要共用一个值。
"""


def _stitch(prev: str, new: str) -> str | None:
    """把滚动出来的下一个窗口接到上一句后面；接不上返回 `None`。见 `ObjectFact.see`。"""
    if new in prev:
        return prev
    if prev in new:
        return new
    for k in range(min(len(prev), len(new)), MIN_STITCH - 1, -1):
        if prev[-k:] == new[:k]:
            return prev + new[k:]
    return None
