"""情景记忆契约：**我在那种画面里选了什么、结果如何。**

作用域是**一次经过**，取回来靠画面相似，有时效。不要和语义记忆混淆——
那答的是"世界是什么样"，自带作用域，域内永远为真（见 `schemas/memory_semantic.py`）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .observation import Observation

MIN_STITCH = 6
"""拼接至少要重叠几个字符。

太短会误拼：两句无关的话结尾和开头撞上三五个字符是常有的事，
而拼错的那一条会以"他说过这句话"的样子进 prompt。GB 一行有十几个字符，
重叠通常是整整一行，所以门槛设高一点几乎不会漏拼。
"""


def _stitch(prev: str, new: str) -> str | None:
    """把滚动出来的下一个窗口接到上一句后面；接不上返回 `None`。

    三种情况都算接得上：新的被包含（对话没动）、新的包含旧的（抄得更全）、
    首尾重叠（滚了一行）。都不是就说明这是**另一句话**，该单独占一条。

    把滚出来的下一个窗口接回上一句，接不上返回 None。
    """
    if new in prev:
        return prev
    if prev in new:
        return new
    for k in range(min(len(prev), len(new)), MIN_STITCH - 1, -1):
        if prev[-k:] == new[:k]:
            return prev + new[k:]
    return None


class Snapshot(BaseModel):
    """一次观察的快照。**里面每一项都必须跨步骤成立。**

    这是它和 `Observation.facts` 唯一的分歧：facts 是"这一帧的全部"，
    快照是"其中还能拿到以后去用的那部分"。

    ## 为什么 walk_map 不在里面

    它天生是**屏幕相对**的：原点跟着人走，走一步同一个 `(7,7)` 就指向另一块地方。
    `MAP_HINT` 里我们自己写着屏幕格"不能跨步骤引用"，早先却把整张图连同带屏幕格的
    地标一起存进了记忆、下一步再喂回去。

    实测代价：模型取回上一步的「民宅的门 (7,7)」，对照当前地图发现 `(7,7)` 是 `#`，
    于是花了 **2235 个 output token、49 秒**反复重数那一行字符串，试图判断
    是记忆错了还是地图错了。**两边都没错，是我们给的数据自相矛盾。**

    ## 那"这一下到底改变了什么"靠什么看

    靠 `position`（全局坐标）和 `neighbors`（相对"我"的四邻）：

    - 撞墙 → 前后 `position` **一模一样**，这条经验的全部价值就在这。
    - 进门 → `position` 里的地图编号变了。
    - "我以为西边能走" → `neighbors["left"]` 白纸黑字写着当时是什么。

    四邻是相对"我"的，不依赖屏幕原点，所以跨步骤永远成立。
    整张图能多告诉你的只是"当时周围什么形状"，而那个信息没有稳定的坐标系可以承载。
    """

    overview: str = Field(default="", description="整体印象，视觉模型给的")
    landmarks: str = Field(
        default="", description="地标，**全局坐标**（`门 x=13 y=5`），来自模拟器内存"
    )
    neighbors: str = Field(
        default="",
        description="四邻各是什么（`北 G 南 . 西 # 东 .`）。**相对『我』，不依赖屏幕原点**，"
        "所以跨步骤成立。它承担的是『我以为那边能走』这类经验的证据",
    )
    position: str = Field(
        default="",
        description="`全局坐标 地图0 x=10 y=2` —— **全局坐标，刻意不用括号写法**。"
        "括号写法留给屏幕格（主角恒在 (4,4)），两者写成同一个样子的话，字面上分不开",
    )
    dialog: str = Field(
        default="", description="对话框里的文字。**跨步骤成立**：那句话说过就是说过了"
    )

    @classmethod
    def of(cls, obs: Observation) -> Snapshot:
        """从观测里抽出快照。**只抽，不加工**——加工过的快照和当时看到的就不是一回事了。"""
        f = obs.facts
        return cls(
            overview=f.get("overview", "") or obs.summary,
            landmarks=f.get("landmarks", ""),
            neighbors=f.get("neighbors", ""),
            position=f.get("where", ""),
            dialog=f.get("dialog_text", ""),
        )

    def render(self, indent: str = "  ") -> str:
        """把这条快照渲染成一段可读、可打分的文本。"""
        lines = []
        if self.position:
            lines.append(f"{indent}位置  {self.position}")
        if self.neighbors:
            lines.append(f"{indent}四邻  {self.neighbors}")
        if self.dialog:
            lines.append(f"{indent}对话  {self.dialog}")
        if self.overview:
            lines.append(f"{indent}概况  {self.overview}")
        if self.landmarks:
            lines.append(f"{indent}地标  {self.landmarks}")
        return "\n".join(lines)

    def same_place_as(self, other: Snapshot) -> bool:
        """两次观察是不是**完全没有区别**。

        位置、四邻、对话框三项全同 = 那一下什么都没发生。
        用这三项而不是全部：`overview` 是模型每次重写的自然语言，同一帧也会不一样，
        拿它比会把"没变"误判成"变了"——实测同一个 frame sha 下它给出过三种不同措辞。

        看两次观察是不是完全没有区别。
        """
        return (
            self.position == other.position
            and self.neighbors == other.neighbors
            and self.dialog == other.dialog
        )


class MemoryEntry(BaseModel):
    """一条情景记忆：**我看到这样的画面，因为这些理由，做了这个动作，然后变成了这样。**

    ## 为什么两头都是完整观察

    只记"结果：你在野外"这种一句话，等于把结果压成了一个没有信息量的标签——
    上一版就是这样，取回十条全长一个样。**结果本身也是一次观察**，
    只有把它完整记下来，这条经验才回答得了"那一下到底改变了什么"。

    代价是上一条的 `after` 和下一条的 `before` 内容重复。这是有意接受的：
    **每条自成一体**，取回时不用去拼上下文，也不依赖别的条目还在不在。

    ## 这仍然只是 episodic

    "这次尝试里发生了什么"，是自己跑出来的轨迹，有时效。

    不要和**语义记忆**混淆：那是"世界是什么样"（"水克火"、"map 0 的 (5,5) 通往 map 37"），
    自带作用域、在作用域内永远为真。也不要和**目标**混淆：目标有完成态，
    凡是有完成态的都不是知识，它属于运行时状态，不进这里。

    程序记忆、skill library（机制二）、值回填（机制三）都还没做。
    """

    before: Snapshot = Field(description="做决定时看到的画面")
    rationale: list[str] = Field(description="当时的理由。**不是完整推理**——那留在 trace 里")
    action: str = Field(description="选了什么，含连按次数，如 `right ×2`")
    after: Snapshot = Field(description="执行之后的画面。**结果也是一次观察**")

    key: str = Field(description="检索键。本阶段用位置占位，机制一接进来时换成状态抽象的语义 key")
    step: int = Field(description="写入时所处的步数")
    episode_id: str = Field(description="这条经验来自哪次尝试")

    # `(episode_id, step)` 就是这条记忆的坐标 —— 一步一条，唯一且语义稳定。
    #
    # 不用 trace 的 `event_id`：那是**记录格式的产物**，取决于这一步之间穿插了
    # 多少别的事件，换个记录粒度就变。`step` 是**轨迹坐标**，而机制三沿轨迹
    # 回填折扣正是按 step 走的——用它，回填时不需要任何转换。

    def render(self, *, reason: bool = True) -> str:
        """渲染成进 prompt 的样子。**检索打分也用它**——

        两处用同一份文本，是为了让"被选中的理由"和"看到的内容"是同一个东西。
        分成两份的话，可能出现"按 A 的内容选中，却把 B 的内容喂进去"，而且不报错。

        `reason=False` 去掉「因为」那一行，**只留发生过的事**。判定器用这一版：
        它需要历史（证据可能出现在三步以前的那一帧里），但**绝不能读到决策者的理由**。
        `rationale` 是被评价者自己的说辞——"我已经和母亲说过话了"这种话一旦进了
        判定器的上下文，成功率就变成它自己发的奖状。
        画面、动作、结果是**发生过的事**，理由是**它对那件事的主张**，两者必须分开。

        渲染成进 prompt 的样子，可选择带不带理由。
        """
        because = "；".join(self.rationale) or "（未给出理由）"
        # **"什么都没发生"要明说，不要让它自己去比。**
        # 前后两份快照摆在一起，理论上对比得出来；实测它不会——
        # 连着三步按 `a` 对着空地，每一步都取回上一步"按 a 没变化"的记忆，
        # 然后照着自己上一步那句"站在门格上按 a 是标准操作"再按一次。
        # 它把过去的 `rationale` 当成了权威，而权威说的话恰恰是错的。
        #
        # 判定是纯比较，我们做得又快又准，就不该留给它。
        after = (
            "  之后变成：**什么都没变**（位置、四邻、对话框全部相同——这个动作没有效果）"
            if self.after.same_place_as(self.before)
            else "  之后变成：\n" + self.after.render()
        )
        lines = [
            f"({self.episode_id}, {self.step}) 当时看到：",
            self.before.render(),
        ]
        if reason:
            lines.append(f"  因为  {because}")
        lines += [f"  做了  {self.action}", after]
        return "\n".join(lines)
