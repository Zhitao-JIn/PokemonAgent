"""单步记忆契约：**我在那种画面里选了什么、结果如何。** 一条 = 一步。

作用域是**一次经过**，取回来靠画面相似，有时效。三类记忆的分工：

    step_memory.py      一条 = 一步       本局全量按顺序交给决策
    episode_memory.py   一条 = 一整局     从别的局里按相关性挑几条
    object_fact.py      一条 = 一格       "世界是什么样"，域内永远为真

这个文件以前叫 `memory_episodic.py`，隔壁那个叫 `memory_episode.py`——
**靠一个词尾区分"一步"和"一局"**，而那是英语的语法差别，不是概念上的差别，
读的人没有任何线索去猜哪个是哪个。现在用 step / episode 分，一眼就分得开。
同理 `MemoryEntry` 改叫 `StepMemory`：「Entry」（条目）等于什么都没说，
而这个类的全部要点恰恰是"一条 = 一步"。
"""

from __future__ import annotations

import unicodedata

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


def _display_width(text: str) -> int:
    """这段文字占几个字符宽。**中日韩字符算两格。**

    对齐要用它而不是 `len()`：标签里中英混排（`位置` 和 `my_hp` 同时出现），
    按字数补空格的话，中文那几行会短一半——而这份文本的**唯一用途**就是让大脑
    逐行对照前后两份快照，列对不齐等于把配对的活又推回给它。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


SNAPSHOT_BLIND: frozenset[str] = frozenset(
    {"known_objects", "knowledge", "cursor_said"}
)
"""**不进快照的字段。** 快照里每一项都必须跨步骤成立，这三项都不成立：

- `known_objects`：跨 episode 的流水，不是"这一帧看到了什么"。
- `knowledge`：语义记忆的检索结果，本来就不是观察。
- `cursor_said`：视觉模型自己那份光标读数，只在它和派生结果不一致时才有。
  它是**给我们数错误率的**，不是这一帧的事实——进了记忆，大脑就会看到
  两个互相矛盾的光标值，然后去调和它们。

除此之外一律照搬。**这里是排除表而不是白名单**，是有意的：新增一个观测字段时，
默认它应该进记忆，需要理由的是把它挡在外面——反过来的话，加字段的人得记得
回来改清单，而忘了改不报错，只表现为某类画面的变化永远看不见。
"""

FIELD_ORDER: tuple[str, ...] = (
    "scene", "overlay", "where", "facing", "neighbors", "landmarks",
    "dialog_text", "options", "cursor",
    "my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp",
    "overview", "walk_map",
)
"""渲染顺序。`walk_map` 和 `overview` 垫底：一个占九行、一个措辞每次都变，
摆在前面会把真正逐行对照的那几项挤下去。`overview` 更靠前——它是这堆字段里唯一由视觉模型自由措辞的一项，
同一帧能给出三种说法，摆在前面会让大脑先读到噪声最大的那行。"""

FIELD_LABEL: dict[str, str] = {
    "where": "位置", "neighbors": "四邻", "dialog_text": "对话",
    "overview": "概况", "landmarks": "地标", "options": "选项",
    "cursor": "光标", "scene": "场景", "overlay": "叠加层", "facing": "朝向",
}
"""字段名 → 中文标签。表外的字段直接用原名，不强行翻译。"""


class Snapshot(BaseModel):
    """一次观察的快照。**里面每一项都必须跨步骤成立。**

    这是它和 `Observation.facts` 唯一的分歧：facts 是"这一帧的全部"，
    快照是"其中还能拿到以后去用的那部分"。

    ## walk_map 进来了——那条旧禁令的前提已经没了

    早先它被挡在外面，理由是**屏幕相对**：原点跟着人走，走一步同一个 `(7,7)` 就指向
    另一块地方。实测代价也记着：模型取回上一步的「民宅的门 (7,7)」，对照当前地图发现
    `(7,7)` 是 `#`，花了 **2235 个 output token、49 秒**反复重数那一行字符串想判断是
    记忆错了还是地图错了——**两边都没错，是我们给的数据自相矛盾。**

    但那是屏幕格时代的账。`TerrainMap.render()` 后来把屏幕格删掉了，行列号**就是全局
    坐标**，和 `where` / `landmarks` 用的是同一套数（见那个方法的说明）。自相矛盾的
    来源没了，禁令的前提也就没了：现在两步的图摆在一起，同一个 `x=12 y=24` 在两张图上
    指的是同一格，**逐格对照是成立的**。

    留着旧禁令的代价反而是实的：地形变化（门开了、挡路的 NPC 走了、进了新区域）
    是"那一下改变了什么"里信息量最大的一类，而它整个看不见。

    代价是 token：一张图九行，一条记忆两张，取回三条就是六张。这笔账目前认了——
    看不见的变化比读得慢贵。真要省，该省的是**取回条数**，不是每条的完整度。

    ## 那"这一下到底改变了什么"靠什么看

    靠 `position`（全局坐标）和 `neighbors`（相对"我"的四邻）：

    - 撞墙 → 前后 `position` **一模一样**，这条经验的全部价值就在这。
    - 进门 → `position` 里的地图编号变了。
    - "我以为西边能走" → `neighbors["left"]` 白纸黑字写着当时是什么。

    四邻是相对"我"的，不依赖屏幕原点，所以跨步骤永远成立。
    整张图能多告诉你的只是"当时周围什么形状"，而那个信息没有稳定的坐标系可以承载。
    """

    status: str = Field(default="", description="那一帧的状态行")
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="那一帧的事实字段，**除去 SNAPSHOT_BLIND 之外原样照搬**。"
        "早先这里是手挑的五个字段（overview/landmarks/neighbors/position/dialog），"
        "那份清单是为野外挑的：战斗帧的 `cursor`、`options`、`my_hp`、`foe_hp` "
        "一个都不在里面，于是「那一下改变了什么」在战斗中永远答不出来。"
        "**字段该由观测决定，不由一份写死的清单决定**",
    )

    # 兼容取用：这两项有具名调用方（`memory/episode/utils.py`）。
    @property
    def overview(self) -> str:
        """整体印象，视觉模型给的。"""
        return self.facts.get("overview", "") or self.status

    @property
    def position(self) -> str:
        """`全局坐标 地图0 x=10 y=2` —— **全局坐标，刻意不用括号写法**。"""
        return self.facts.get("where", "")

    @classmethod
    def of(cls, obs: Observation) -> Snapshot:
        """从观测里抽出快照。**只抽，不加工**——加工过的快照和当时看到的就不是一回事了。"""
        return cls(
            status=obs.status,
            facts={k: v for k, v in obs.facts.items() if k not in SNAPSHOT_BLIND},
        )

    def render(self, indent: str = "  ") -> str:
        """把这条快照渲染成一段可读、可打分的文本。

        **按 `FIELD_ORDER` 排，表外的字段按名字排在后面。** 顺序固定不是为了好看：
        前后两份快照要摆在一起给大脑比对，同一个字段在两份里必须出现在同一个相对
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


class StepMemory(BaseModel):
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
        # **前后两份都完整摆出来，结论留给大脑。**
        #
        # 这里曾经有一次 `same_place_as(before, after)`：前后一样就折叠成一句
        # 「**什么都没变**（这个动作没有效果）」。折叠掉的理由是实测——连着三步按 `a`
        # 对着空地，它取回上一步的记忆却不去对比，照着自己上一步那句
        # 「站在门格上按 `a` 是标准操作」再按一次。
        #
        # 但那个比较**只看位置、四邻、对话框**，而这三项是为野外挑的。战斗帧里它们
        # 是进战斗前残留的野外值，恒等——于是战斗中每一步都被宣布成"这个动作没有效果"，
        # 哪怕光标确实移动了。实测大脑照单全收：它引用这句话，推翻自己上一步正确的
        # 按键，然后编出一套能解释"为什么没生效"的菜单模型。
        #
        # **错误的结论比没有结论贵得多。** 一句加粗的判断，大脑对它的信任度正好是
        # 我们承诺的那么高；而它是不是对的，取决于比的是不是这一帧真正会变的字段——
        # 那个清单不可能手工穷举。所以现在只摆事实：两份快照字段对齐、顺序固定，
        # 变没变由它自己读。防不去对比的那条，改在决策 prompt 里说（`decide.md`）。
        lines = [
            f"({self.episode_id}, {self.step}) 当时看到：",
            self.before.render(),
        ]
        if reason:
            lines.append(f"  因为  {because}")
        lines += [f"  做了  {self.action}", "  之后变成：\n" + self.after.render()]
        return "\n".join(lines)
