"""跨层传递的数据模型。

这里的每个模型都是**接口契约的一部分**：只要出现在 `interfaces/` 的签名里，
它的字段含义就是各层之间的共识，改字段等于改接口。

设计约束（来自 CLAUDE.md 铁律 4）：跨层一律用这里的模型，不用裸 dict。

## 这个文件装着两类东西，边界在中间那道分隔线

上半部分是**跨层契约**：`Task` / `Observation` / `Action` / `TraceEvent` 等，
它们出现在 `interfaces/` 的签名里，改字段等于改接口。

下半部分是**感知层的模型**：`Scene` / `Overlay` / `ScreenState` 等。
它们一次都没出现在任何 Port 的签名里——`ScreenState` 由 `PyBoyWorld` 产出、
就地压成 `Observation.facts` 里的字符串，不跨层传递。

**大脑不该 import 下半部分的任何东西。** 以前这是导入图强制的（`react.py` 只认识
`core`，拿不到 `Scene` 这个名字），合并之后只剩纪律。一旦大脑开始按 `scene` 分支，
分层就名存实亡了——这条现在得靠人守。

两半的版本纪律也不同：上半由 `TRACE_SCHEMA_VERSION` 管事件形状，
下半的 `Scene` / `Overlay` 受 append-only 约束（机制三的 `(state-key, action) -> value`
一旦开始积累，枚举值只能增不能改）。改任何一边之前先看清自己在哪一半。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class Task(BaseModel):
    """一个有明确成败判据的任务。**episode 的边界就是任务的边界。**

    为什么不用"通关"做 episode：通关是几千步、只产出一个 0/1 结果，
    机制三的蒙特卡洛回填折扣一路乘下去，回填到前期步骤上几乎是噪声；
    评测也只能报"通关了没有"这一个二值数字。任务级则能报成功率、失败模式分布、
    有记忆 vs 无记忆的对比。

    但任务有**下界**：必须长到单靠上下文装不下、必须跨任务复用经验才做得好，
    否则记忆架构就失去了存在理由。"打赢二号道馆"合适，"和 NPC 说句话"不合适。
    """

    task_id: str = Field(description="任务标识，同一任务的多次尝试共用它")
    goal: str = Field(description="给 LLM 读的目标描述，会进 prompt")
    success_criteria: str = Field(description="成败判据的人类可读描述；判定由 world 实现")
    max_steps: int = Field(description="步数上限，超出即判失败。> 0")


BUTTON_FACING: dict[str, str] = {
    "up": "north", "down": "south", "left": "west", "right": "east",
}
"""方向键 → 朝向。**朝向是我们自己的动作推出来的，不是看出来的。**

宝可梦里按方向键，撞墙时人也会转过去（只是不移动），所以"按过 up"就等于"面朝北"，
没有例外。实测让 VLM 读朝向是 8 步 8 次全错。

放在 core 而不是 world，是因为**两处都要用**：world 用它更新 `facing`，
工具层用它算"这一步走的是哪个方向"——而那两件事必须用同一张表。
"""

FACING_STEP: dict[str, tuple[int, int]] = {
    "north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0),
}
"""朝向 → 全局坐标的位移。**`a` 作用在面朝的那一格上**，所以要拿这张表算出
"我刚才是在跟谁互动"。y 向下增大，和 `walk_map` 的行号一致。"""

FACING_OPPOSITE: dict[str, str] = {
    "north": "south", "south": "north", "west": "east", "east": "west",
}
"""朝向的反面。**用来说清"我站在它的哪一边"**：面朝北去碰一个东西，
说明我人在它的南边。姿势要写成"我站在哪"而不是"我朝哪看"——
下次想复现这个动作，模型得先知道该走到哪一格去。"""

FACING_CN: dict[str, str] = {
    "north": "北", "south": "南", "west": "西", "east": "东",
}
"""渲染姿势用。这些字符串会进 prompt，所以写成中文方位而不是 `north`。"""

KIND_DOOR, KIND_SIGN, KIND_PERSON = "门", "招牌", "人"
"""地标的三种类型。**下半部分那组 `DOOR/SIGN/PERSON` 是地图上的字符 `D/S/N`，
不是这个**——两组名字撞过一次，症状是门的分支静默不生效。"""

WARPED = "换到地图"
"""门被打开时结果字符串的前缀。**判"成功"就靠它**，所以只能有一处定义。"""

DOOR_POSES: tuple[str, ...] = tuple(
    [f"站在上面按{k}" for k in ("up", "down", "left", "right")]
    + [f"站在{FACING_CN[FACING_OPPOSITE[f]]}边按{k}"
       for k, f in BUTTON_FACING.items()]
)
"""一扇门总共有几种碰法：**两种站位 × 四个方向 = 8 种，穷尽**。

穷尽这件事是这一版的关键。有了全集才算得出**「还没试过的是哪几种」**——
而那正是 agent 卡住时唯一缺的信息。实测它在两扇挨着的门之间来回踱步，
`down` 一次都没试过（`neighbors` 说南边是 `#`），
如果档案里当时写着"没试过：down"，它不会卡。

顺序是刻意的：先列"站在上面"。室内出口只有那一种走法，
而它恰恰是 agent 最想不到的一种。
"""

MAX_TRIED = len(DOOR_POSES)
"""一个对象最多记几种姿势 = 姿势的全集大小。

早一版是 4，那是当"最近用过"的滑动窗口用的——但**试过的姿势不该被淘汰**：
淘汰一条就等于把它变回"没试过"，agent 会重试一个已经排除的方向，
而这份档案存在的全部意义就是让它别再重试。
"""

MAX_OBJECT_LINES = 4
"""一个对象最多记几句话。

有上限不是怕内存，是怕 prompt：这些条目每一帧都要发，而一个 NPC 在剧情推进时
可能说几十句。留最近几句够用了——**要点是"这是谁"，不是复述完整台词**。
"""


class Place(BaseModel):
    """地图上的一个格子。**这是全项目唯一的"位置"表示。**

    做成模型而不是三个散字段，是因为它现在**承载记忆的键**：
    交互记忆按 `(map_id, x, y)` 索引，那三个数必须整体传递、整体比较。
    散着传总有一天会漏掉 `map_id`，而漏掉之后两张地图上的同一个坐标会撞在一起——
    那种错不报错，只会让记忆开始张冠李戴。
    """

    map_id: int
    x: int
    y: int

    def step_toward(self, facing: str) -> Place:
        """面朝 `facing` 时，`a` 会作用到的那一格。"""
        dx, dy = FACING_STEP[facing]
        return Place(map_id=self.map_id, x=self.x + dx, y=self.y + dy)

    @property
    def key(self) -> str:
        """记忆的键。**跨 episode 稳定**——同一张地图上的同一格永远是同一个键。"""
        return f"{self.map_id}:{self.x}:{self.y}"

    def render(self) -> str:
        """**全局坐标写成 `x= y=`，不用括号** —— 括号写法留给屏幕格。"""
        return f"全局坐标 地图{self.map_id} x={self.x} y={self.y}"


def _compact(poses: list[str]) -> str:
    """把姿势列表压短一点。这几行每一帧都要发，`站在上面按` 重复四遍是纯浪费。

        ['站在上面按up', '站在上面按left', '站在南边按up']
        -> '站在上面按 up/left；站在南边按up'
    """
    on = [p.removeprefix("站在上面按") for p in poses if p.startswith("站在上面按")]
    side = [p for p in poses if not p.startswith("站在上面按")]
    out = ([f"站在上面按 {'/'.join(on)}"] if on else []) + side
    return "；".join(out)


class Landmark(BaseModel):
    """屏幕上一个值得记住的东西：门 / 招牌 / 人。类型和位置都来自模拟器内存。

    **没有名字。** 名字在总览画面里没有可观测的证据，只能靠走过去交互再记住——
    那正是 `ObjectNote` 的活。
    """

    kind: str = Field(description="门 / 招牌 / 人")
    place: Place

    def render(self) -> str:
        return f"{self.kind} x={self.place.x} y={self.place.y}"


class ObjectNote(BaseModel):
    """**交互记忆**：某一格上的东西，跟它互动会得到什么。

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
    最后都会被当成事实反复使用。这里存的是 `tried`：**姿势 → 结果**，
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
    leads_to: int | None = Field(
        default=None,
        description="这扇门通往哪张地图。**只有门有，而且是走进去之后算出来的**："
        "`before.map_id != after.map_id` 时，答案就是 `after` 的那个数。"
        "纯算术，不会错——而且不是白送的，是它自己走进去换来的",
    )
    tried: dict[str, str] = Field(
        default_factory=dict,
        description="**姿势 → 结果**，记「怎么碰它才有用」。"
        "键形如 `站在南边按up` / `站在上面按up`，值形如 `换到地图37` / `过去了` / `没动`。"
        "两边都是算出来的：键来自 `before.place` 和它的相对位置，"
        "值来自 `before.place` 和 `after.place` 一减",
    )

    @property
    def opened_by(self) -> str:
        """打开这扇门的那个姿势；没打开过就是空串。

        **成功是算出来的，不是模型判断的。** 每种 label 的成功长什么样是固定的：
        门 = `map_id` 变了，人/招牌 = 弹出文字。所以不需要把一串流水交给模型
        让它自己看出哪条是成功——直接把结论写出来。
        """
        return next((p for p, r in self.tried.items() if r.startswith(WARPED)), "")

    @property
    def untried(self) -> list[str]:
        """还没试过的姿势。**只有门有意义**（人和招牌只有"按 a"一种碰法）。"""
        return [p for p in DOOR_POSES if p not in self.tried]

    def try_it(self, pose: str, result: str) -> None:
        """记下一种姿势的结果。**同一姿势以最新的为准。**

        不是"第一次记下就不改"，因为结果真的会变：一扇本来锁着的门后来开了、
        一条本来有人挡着的路后来通了。旧结论留着比没有更糟——
        它会让 agent 反复绕开一条已经通了的路。
        """
        if not pose or not result:
            return
        self.tried.pop(pose, None)   # 重新插到末尾，让淘汰按"最近用过"走
        self.tried[pose] = result
        for stale in list(self.tried)[:-MAX_TRIED]:
            del self.tried[stale]

    def see(self, line: str) -> None:
        """记下一句。已经见过就不重复记——重复的文本会被模型当成强证据。"""
        text = line.strip()
        if text and text not in self.lines:
            self.lines.append(text)
        del self.lines[:-MAX_OBJECT_LINES]

    def _door_status(self) -> list[str]:
        """门的那几段。**给结论，不给流水。**

        门的成功判据是固定的（`map_id` 变了），所以这里直接算出三件事：
        打开它的姿势是哪个、哪些姿势已经排除、还剩哪些没试。
        模型不需要从一串"站在上面按right→从这一格走开了"里自己悟出结论——
        而实测它悟出来的是反的：把"走开了"读成了"穿过去了"，
        在两扇挨着的门之间来回踱步。

        没打开过时，**"还没试过"那一段比"试过没用"更要紧**：
        它是这扇门唯一的待办清单，也是死循环唯一的出口。
        """
        opened = self.opened_by
        if opened:
            return [f"**{opened}** 能过去 → 地图{self.leads_to}"]
        if not self.tried:
            # 一次都没试过时不列全集：那 8 条对每一扇没碰过的门都一模一样，
            # 每帧发一遍就是纯噪声。**"还没试过的是哪几种"只有在它开始试之后才有信息量**，
            # 而那也正是它可能卡住的时候。
            return ["**还没打开过**"]
        out = ["**还没打开过**", "试过没用：" + _compact(list(self.tried))]
        if self.untried:
            # 八种全试遍了还没开：这扇门就是打不开（剧情没到、或者它根本是装饰）。
            # 那时候写"还没试过：（没有）"是废话，删掉这一段本身就是结论。
            out.append("**还没试过**：" + _compact(self.untried))
        return out

    def render(self) -> str:
        """渲染成 `known_objects` 里的一行。

        **"还没互动过"也要写出来。** 这份档案最有价值的一类条目正是它：
        "这里有一扇门，我见过 7 次，一次都没进去过"——那是它自己的待办清单，
        而没有这条信息，它只能靠 `landmarks` 看到那里有扇门，
        分不出哪扇是探索过的、哪扇是新的。
        """
        parts: list[str] = []
        if self.lines:
            parts.append(" / ".join(self.lines))
        if self.landmark.kind == KIND_DOOR:
            parts.extend(self._door_status())
        elif self.tried:
            parts.append("；".join(f"{k}→{v}" for k, v in self.tried.items()))
        if not parts:
            parts.append("互动过但没出现文字" if self.touched else "**还没互动过**")
        return (
            f"{self.landmark.place.render()} 的「{self.landmark.kind}」"
            f" → {'；'.join(parts)}"
            f"（见过 {self.seen} 次，互动 {self.touched} 次）"
        )


class Observation(BaseModel):
    """大脑在某一步看到的世界。

    只放**大脑决策需要的**信息。原始画面、模拟器内部状态不进这里——
    那些属于 harness，大脑看不到也不该看到。
    """

    step: int = Field(description="本 episode 内的第几步，从 0 开始")
    place: Place | None = Field(
        default=None,
        description="主角所在的格子。**结构化的那一份**——"
        "`facts[\"where\"]` 是它渲染出来给模型读的文本，"
        "而记忆的键要拿这三个数去算，不能靠反解字符串",
    )
    summary: str = Field(description="给 LLM 读的自然语言状态描述")
    facts: dict[str, str] = Field(
        default_factory=dict,
        description="结构化状态字段（位置、HP、持有道具…）。机制一的 state key 未来从这里派生",
    )
    done: bool = Field(default=False, description="episode 是否已终止（成功、失败或超步数）")
    success: bool = Field(
        default=False,
        description="任务是否达成。**只在 done 为 True 时有意义**，否则恒为 False",
    )


class ActionSpace(BaseModel):
    """当前状态下**可用**的动作集合（state-dependent action masking）。

    注意语义：这不是"全部动作"，是"此刻允许的动作"。动作空间不增长，
    增长的是掩码之外的 skill library（本阶段不做）。
    """

    intents: list[Intent] = Field(
        default_factory=lambda: [Intent.PRESS],
        description="这一轮允许哪几类动作。**由 Harness 填**——"
        "能不能拆子目标取决于栈有多深，那是循环的事，工具层不知道",
    )
    names: list[str] = Field(description="可用按键名，非空")
    descriptions: dict[str, str] = Field(
        default_factory=dict, description="动作名 -> 给 LLM 读的说明"
    )
    note: str = Field(
        default="",
        description="关于整个动作空间的说明（如连按怎么用），不属于任何单个动作。"
        "**必须有这个字段**：prompt 只渲染 names 里的动作说明，"
        "塞进 descriptions 的额外条目永远不会被渲染出去",
    )

    def contains(self, name: str) -> bool:
        return name in self.names


MAX_RATIONALE = 3
"""一个动作最多带几条论据。

抽成常量是因为它有两个执行点——`Action` 的字段约束（数据契约）和 `_parse`
（外部输入校验）。两处必须同源，否则模型给 4 条时会得到一个自相矛盾的系统：
解析器放行、构造时炸。
"""


class Intent(str, Enum):
    """大脑这一轮想做哪一类事。**它是图的分派依据。**

    分成三类而不是把它们都塞进按键里，是因为它们**代价和后果完全不同**：
    只有 `PRESS` 推进世界（不可逆），另外两类只改变大脑自己的处境。
    分开之后"它花了多少轮在想、多少轮在走"是可以直接从 trace 数出来的。

    往里加第四类（读记忆、写记忆、调工具）时，加的是一个枚举值加一个图节点，
    `choose()` 和 prompt 的形状不变——这是把它做成枚举而不是布尔标志的收益。
    """

    PRESS = "press"
    """按键，推进世界。**唯一不可逆的一类。**"""

    PUSH_GOAL = "push_goal"
    """把当前目标拆出一个更近的子目标压进栈。不推进世界。"""

    INSPECT = "inspect"
    """对同一帧再问一次视觉模型，问一个具体的问题。不推进世界。

    **必须带 `focus`**：不带的话它就是把同一帧原样再看一遍——
    `perceive()` 是帧内缓存的，返回的字节完全一样，不产生任何新信息，
    而模型在拿不准的时候一定会选它，然后下一轮看到同样的画面再选一次。
    带上具体问题、走另一份 prompt，它才真的产出新事实，也才值那次钱。
    """


class Goal(BaseModel):
    """一个目标：想达成什么，以及**怎么算达成**。

    两样一起给，不能只给前者：判定器的输入就是这两项，没有判据它无从判断，
    只能凭"看起来差不多了"回答——而那正是成功率会被污染的地方。

    所以大脑压子目标时必须同时写出判据。写不出判据的子目标，
    本身就说明它没想清楚要什么。
    """

    goal: str = Field(min_length=1, description="想达成什么，一句话")
    criteria: str = Field(
        min_length=1, description="画面上出现什么才算达成。**要能只看一帧就判断**"
    )


class Action(BaseModel):
    """大脑选出的一个动作。

    它带着三样东西过来，服务于三个不同的消费方，**不要合并**：

    - `name` / `args` —— 给世界执行。
    - `thought` —— 完整推理，**只进 trace**，不参与任何后续决策。
      不设长度上限：它的长度就是模型这一步的算力，压缩它压的是思考本身，
      不是日志体积。
    - `rationale` —— 最能支持这个动作的论据，**进 memory**，会被未来的步骤检索回去。

    为什么进记忆的是论据而不是结论：结论（"所以该捡药水"）可以从 `name` 反推，
    存进去等于把同一件事存两遍；论据（"地上有药水而我手上没有"）才是 `name`
    里没有的信息。更要紧的是论据是**适用条件**——未来取回这条经验时可以检查
    它现在还成不成立，结论做不到这件事。

    论据一律按**有时效**处理，不区分持久与否。持久知识（"馆主是火属性"）的
    跨 episode 复用属于 skill library（机制二），本阶段不做。
    """

    intent: Intent = Field(
        default=Intent.PRESS,
        description="这一轮做哪一类事。**分派靠它**，`name` 只在 PRESS 时有意义",
    )
    name: str = Field(
        default="", description="按键名，必须来自当时的 ActionSpace。只在 PRESS 时有意义"
    )
    args: dict[str, str] = Field(
        default_factory=dict, description="按键参数，目前只有 `times`（连按几次）"
    )
    goal: Goal | None = Field(
        default=None, description="要压进目标栈的子目标。只在 PUSH_GOAL 时有意义"
    )
    focus: str = Field(
        default="", description="想细看什么，一句话。只在 INSPECT 时有意义"
    )
    thought: str = Field(
        min_length=1,
        description="选择该动作的完整推理。只进 trace，不进 memory，不影响后续决策",
    )
    rationale: list[str] = Field(
        min_length=1,
        max_length=MAX_RATIONALE,
        description=f"最能支持该动作的论据，1-{MAX_RATIONALE} 条。"
        "进 memory；经验能否迁移全看它",
    )

    @model_validator(mode="after")
    def _fields_must_match_the_intent(self) -> Action:
        """每种 intent 的必填字段不同，**在这里挡住**，不要漏到分派的时候。

        漏过去的话，`push_goal` 少了 `goal` 会在 Harness 里 assert 崩掉——
        那是把**模型的输出问题**报成了**我们自己的契约违约**，看堆栈会指错方向。
        在这里失败则走 `ParseFailure`，会被重试，也会按失败模式统计。
        """
        if self.intent is Intent.PRESS and not self.name:
            raise ValueError("intent=press 必须给 action（按键名）")
        if self.intent is Intent.PUSH_GOAL and self.goal is None:
            raise ValueError("intent=push_goal 必须给 goal 和 criteria")
        if self.intent is Intent.INSPECT and not self.focus.strip():
            raise ValueError("intent=inspect 必须给 focus（想细看什么）")
        return self


class ToolResult(BaseModel):
    """一次动作执行的结果。

    ## 这里曾经有一个 `ok`

    含义是"这个动作有没有产生预期效果"（撞墙 = False）。在 `PyBoyWorld` 上它被
    写死成 `True`，因为从像素判断"这一下有没有改变世界"没有便宜可靠的办法——
    画面本身就有动画，比对不出因果。

    **一个恒为真的布尔值比没有更糟**：它出现在事件流里、出现在控制台的判断分支里，
    让人以为那里有信息，而实际上每一条都是 True。

    要让它诚实，唯一的办法是读内存里的坐标（走没走动）——但那是为一个**没有消费方**
    的字段新增一处内存依赖。判断动作有没有生效，本来就该由**前后两次观察的对比**
    来回答，而那件事记忆层已经在做了（`MemoryEntry` 两头各存一份完整快照）。

    所以删掉，不是补上。
    """

    message: str = Field(default="", description="给 LLM 读的结果描述")
    observation: Observation | None = Field(
        default=None, description="执行后的新观测；None 表示调用方需另行 perceive()"
    )


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

    dialog: str = Field(
        default="", description="对话框里的文字。**跨步骤成立**：那句话说过就是说过了"
    )

    def render(self, indent: str = "  ") -> str:
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

    不要和 **semantic** 混淆：那是"世界是什么样"（"水克火"、"map 0 的 (5,5) 通往 map 37"），
    自带作用域、在作用域内永远为真。也不要和**目标**混淆：目标有完成态，
    凡是有完成态的都不是知识，它属于运行时状态，不进这里。

    semantic 层、skill library（机制二）、值回填（机制三）都还没做。
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


class EpisodeOutcome(BaseModel):
    """一次任务尝试的最终结果。

    这是评测与机制三的输入：成功率按 task_id 分组统计，
    MC 回填拿 success 作为 episode 的最终回报沿轨迹往回传。
    """

    episode_id: str = Field(description="本次尝试的标识")
    task_id: str = Field(description="尝试的是哪个任务")
    success: bool
    steps: int = Field(description="实际用了多少步")
    reason: str = Field(description="终止原因：success / failed / max_steps_exceeded / error")


TRACE_SCHEMA_VERSION = 2
"""事件形状的版本号。

**必须有。** 事件形状还会变（这一版就是第二版），而老 JSONL 被新解析器读时
不会报错，只会**静默读错**——少一个字段就当它是空的，多一个就忽略。
版本号让「这批数据是旧格式」变成一句可判断的话。
"""


class Source(str, Enum):
    """事件由哪一层产生。

    **每种聚合几乎都要按它切**：感知和决策各烧多少 token、失败集中在哪一层、
    延迟花在哪。放信封不放 payload，就是因为它是横切的。
    """

    PERCEPTION = "perception"   # 视觉模型这条链
    DECISION = "decision"       # 文本模型这条链
    HARNESS = "harness"         # 掩码、记忆、生命周期
    WORLD = "world"             # 模拟器
    JUDGE = "judge"             # 成败判定 —— 和决策分开记账，才算得出它自己的准确率


class EventType(str, Enum):
    """trace 事件类型。"""

    EPISODE_START = "episode_start"
    EPISODE_END = "episode_end"
    OBSERVE = "observe"
    MODEL_CALL = "model_call"
    THINK = "think"
    ACT = "act"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    OBJECT_NOTE = "object_note"
    """记下了「某一格的东西给了什么」。**和 MEMORY_WRITE 分开**：

    它们是两种记忆（一次经过 vs 那一格本身），寿命和用途都不同。
    混成一类就数不出"它认识了多少个东西"——而那正是交互记忆有没有用的直接指标。
    """
    INSPECT = "inspect"
    """细看了一次。**和 OBSERVE 分开**：它是大脑主动要的，不是每步必发的那一帧。

    混在一起就算不出「它多久要细看一次」，而那正是判断这个动作值不值那次钱的依据。
    """
    GOAL_PUSH = "goal_push"
    GOAL_POP = "goal_pop"
    """目标栈的进出。

    分成两个类型而不是一个带方向的字段：**"它拆了几层"和"它完成了几层"是两个数**，
    而拆得多完成得少正是目标栈失控的样子——按类型计数一眼就看得出来。
    """
    ERROR = "error"
    CHECKPOINT = "checkpoint"


class TraceEvent(BaseModel):
    """追加写的 trace 事件。

    这是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因
    的共同底座，所以它是**不可变的事件**，不是可变的状态快照——
    不要往里加"当前状态"这类字段，那样就没法重放了。
    """

    event_id: int = Field(description="全局单调递增，SSE 断线重连靠它补发。**排序的唯一依据**")
    run_id: str = Field(
        description="哪一次实验。**manifest 的 join key**——"
        "没有它，一份记着模型与 prompt 的 manifest 和一堆事件对不上"
    )
    episode_id: str = Field(description="所属 episode")
    step: int = Field(description="发生在第几步。**不是主键**——一步内有多条事件")
    type: EventType
    source: Source = Field(description="由哪一层产生。成本拆分与失败归因都按它切")
    payload: dict[str, str] = Field(default_factory=dict, description="该类型的结构化内容")
    ts: float = Field(
        description="Unix 时间戳，秒。用于算延迟与对齐外部日志；"
        "**不能替代 event_id 排序**——同毫秒多条事件、时钟回拨都会让时间序失真"
    )
    schema_version: int = Field(default=TRACE_SCHEMA_VERSION)


# =====================================================================
#  以下是**感知层**的模型 —— 一帧画面被解析成什么
#
#  它们不跨层：由 `PyBoyWorld` 产出并就地转成 `Observation`，
#  一次都不出现在 `interfaces/` 的签名里。大脑看的是上半部分的 `Observation`。
# =====================================================================

class Scene(str, Enum):
    """你在什么场合。决定**要读哪些字段**。"""

    FIELD = "field"          # 野外：城镇、路线，可自由走动
    INDOOR = "indoor"        # 室内：研究所、民宅、道馆内部
    BATTLE = "battle"        # 战斗中
    MENU = "menu"            # 系统菜单：START 菜单 / 背包 / 精灵列表 / 状态页
    SHOP = "shop"            # 商店买卖界面
    TRANSITION = "transition"  # 过场：黑屏、进出门、白闪


class Overlay(str, Enum):
    """屏幕上盖着什么等你操作。决定**可以按什么键**。"""

    NONE = "none"      # 没有弹出层，直接操作角色
    DIALOG = "dialog"  # 对话框：一段文本等你推进
    CHOICE = "choice"  # 选择框：一组选项 + 光标


# ---- 两张表：二元组的收益就兑现在这里 ----

OVERLAY_ACTIONS: dict[Overlay, tuple[str, ...]] = {
    Overlay.NONE: ("up", "down", "left", "right", "a", "start"),
    Overlay.DIALOG: ("a",),                      # 方向键无效，只能推进
    Overlay.CHOICE: ("up", "down", "a", "b"),    # 移光标 / 确认 / 取消
}
"""动作掩码**只看 overlay**，与 scene 无关。

这就是拆成二元组最直接的回报：三条规则覆盖所有场合，
而不是每个"场合 × 叠加层"的组合各写一遍。
"""

SCENE_FIELDS: dict[Scene, tuple[str, ...]] = {
    # 野外与室内**没有 fields**：地形来自模拟器内存（`world/ram.py`），
    # 语义来自 `overview` 和 `landmarks`。
    #
    # 曾经这里是 `facing, north, south, east, west, landmarks`，实测全是噪声：
    # `north: grass ×3` 在主角连走六步的过程中一字未变——它根本不是位置的函数，
    # 是"这张图上半部分是草"的函数。字段名承诺的是**测量**，VLM 交付的是**描述**，
    # 两者差一个数量级，不是把 prompt 写好就能弥合的。
    #
    # `facing` 更不该问模型：朝向就是最后一次按的方向键，world 自己知道，
    # 是确定的量，问模型等于把一个已知量换成一个 8/8 全错的猜测。
    Scene.FIELD: (),
    Scene.INDOOR: (),
    Scene.BATTLE: ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp"),
    Scene.MENU: ("title",),
    Scene.SHOP: ("money", "items"),
    Scene.TRANSITION: (),
}
"""每个场合期望读到哪些字段。

**这是数据不是类型**：给某个 scene 加一个字段，不改变任何枚举值，
所以不触发 append-only 的约束。字段名进 prompt 告诉 VLM 该填什么，
填出来的值进 `ScreenState.fields`。
"""


GRID_COLS, GRID_ROWS = 10, 9
"""屏幕上有几列几行格子。160/16 = 10，144/16 = 9。"""

PLAYER_CELL = (4, 4)
"""主角在屏幕上的格子坐标 `(col, row)`，**是个常量**。

宝可梦红的镜头锁死在主角身上，所以他在屏幕上的位置永远不变——28 张真实截图
（野外、室内、有无对话框）无一例外。

这一条把感知任务降了一个维度：**模型不需要定位主角**，只需要读格子内容。
它同时提供一个免费的自检位——模型把 `@` 放到别处，说明它的坐标系整个是错的，
这一帧判废重试，不必等 agent 撞墙才发现。
"""

PLAYER_MARK = "@"
WALKABLE, BLOCKED = ".", "#"

DOOR, SIGN, PERSON, GRASS = "D", "S", "N", "G"

TERRAIN_MEANING: dict[str, str] = {
    ".": "能走",
    "G": "草丛，能走，走进去会遇野生宝可梦",
    "D": "门 / 入口 / 楼梯，走进去会切换到另一张地图",
    "S": "招牌或可调查物，走不过去；面朝它按 A 可以看",
    "N": "人，走不过去；面朝它按 A 可以对话",
    "#": "墙 / 树 / 建筑 / 水面，走不过去",
    "@": "你自己。图上标 @ 的那一格就是 `where` 那一行给的坐标",
}
"""地形符号的含义。**每一个都来自模拟器内存，没有一个是认出来的。**

    .  #   ← tile id 查 tileset 的可通行表（游戏自己的 CheckTilePassable）
    G      ← tileset 头里的 wGrassTile
    D      ← 地图头的 warp 表（还带着通往哪张地图）
    S      ← 地图头的 sign 表
    N      ← 精灵表 wSpriteStateData1
    @      ← 常量，镜头锁在主角身上

这就是这一版和前三版的根本差别：视觉模型反复读错的东西（墙认成门、窗户认成人），
在这里**根本不存在"认"这个动作**。

这份 dict 同时是 prompt 里的图例来源（`terrain_legend()`），两边共用一份——
各写一份必然漂移，而模型和大脑用两套字典这种错不会报错，只会静默互相误解。
"""

MAP_CHARS = frozenset(TERRAIN_MEANING)


def terrain_legend() -> str:
    """渲染成 prompt 和动作说明里的图例。"""
    return "\n".join(f"- `{ch}` {text}" for ch, text in TERRAIN_MEANING.items())


class TerrainMap(BaseModel):
    """从模拟器内存读出的通行图。**不是识别出来的。**

    它抄的是游戏自己的碰撞判定（`CheckTilePassable`）：取目标格的 tile id，
    在 tileset 的可通行表里查找。没有阈值、没有概率、没有识别——
    几何这一维因此是 100% 而不是 87%。

    **它不是 `Observation`**：`Observation` 是大脑看到的东西，这个是感知层的中间物，
    由 `PyBoyWorld` 转成 `Observation.facts` 里的一段文本。
    """

    cells: list[str] = Field(
        description=f"{GRID_ROWS} 行、每行 {GRID_COLS} 个字符，取自 {sorted(MAP_CHARS)}"
    )
    map_id: int = Field(description="当前地图编号（wCurMap）")
    player_x: int = Field(description="主角在地图里的 X 格坐标（wXCoord）")
    player_y: int = Field(description="主角在地图里的 Y 格坐标（wYCoord）")
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
        return self.cells[row][col]

    def neighbors(self) -> dict[str, str]:
        """四个方向键各自通往的那一格是什么。

        单独给一个方法，因为这四格和其余 86 格不是一回事：它们决定这一步能不能动。
        """
        col, row = PLAYER_CELL
        return {
            "up": self.at(col, row - 1), "down": self.at(col, row + 1),
            "left": self.at(col - 1, row), "right": self.at(col + 1, row),
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

        ## 没有列号，这是故意的

        行号能横着写（一行一个数，写在左边），列号不能——全局 x 是两三位数，
        而一列只有一个字符宽。试过把列号竖着摞成两行（十位一行、个位一行），
        **模型读不动**：那要求它对着某一列纵向拼数字，比原来的换算还难。

        所以这里干脆不给列号，只在开头写一句这一屏覆盖到哪。
        代价是它没法在图上直接读出某一列的 x——**而这个代价是零**，
        因为它本来就不该在图上数格子找东西：门、招牌、人的确切坐标
        `landmarks` 和 `known_objects` 里已经写好了，四邻 `neighbors` 也已经算好了。
        这张图剩下的用处是**看形状**：往那个方向走得通吗、哪边是死路。
        看形状不需要列号。

        ## 格子之间不加空格

        曾经用 `" ".join(...)` 排得整齐些，实测模型把那些空格也当成了格子——
        一行 10 格看成 19 格，坐标全线错位。
        """
        col, row = PLAYER_CELL
        ys = [self.player_y + r - row for r in range(GRID_ROWS)]
        left, right = self.player_x - col, self.player_x + GRID_COLS - 1 - col
        gutter = max(len(str(y)) for y in ys)

        lines = [f"这一屏：x 从 {left} 到 {right}，y 从 {ys[0]} 到 {ys[-1]}"]
        for r, line in enumerate(self.cells):
            chars = list(line)
            if r == row:
                chars[col] = PLAYER_MARK
            lines.append(f"y={ys[r]:<{gutter}} " + "".join(chars))
        return "\n".join(lines)

    def landmarks(self) -> list[Landmark]:
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
        - **经验**：走进去看见了什么，然后记住。**只有这一个是对的**，而它还没做。

        所以现在只给类型和位置。等记忆系统能把"进过 x=13 y=5 那扇门，里面是小茂家"
        沉淀下来，名字才会从那边长出来。
        """
        pc, pr = PLAYER_CELL
        kind = {DOOR: "门", SIGN: "招牌", PERSON: "人"}
        here = self.place()
        return [
            Landmark(
                kind=kind[ch],
                place=Place(map_id=here.map_id,
                            x=here.x + (c - pc), y=here.y + (r - pr)),
            )
            for r, line in enumerate(self.cells)
            for c, ch in enumerate(line)
            if ch in (DOOR, SIGN, PERSON)
        ]

    def place(self) -> Place:
        """主角所在的格子。"""
        return Place(map_id=self.map_id, x=self.player_x, y=self.player_y)

    def render_neighbors(self) -> str:
        """四邻渲染成一行。**相对『我』的方向，不依赖屏幕原点，所以能进记忆。**"""
        n = self.neighbors()
        名 = {"up": "北", "down": "南", "left": "西", "right": "东"}
        return " ".join(f"{名[d]} {n[d]}" for d in ("up", "down", "left", "right"))

    def render_landmarks(self) -> str:
        """渲染成 facts 里那一行。**全局坐标写成 `x= y=`**，和屏幕格的括号写法分开。"""
        return "; ".join(m.render() for m in self.landmarks())


NEEDS_OVERVIEW = (Scene.FIELD, Scene.INDOOR)
"""哪些场合必须给 `overview`。

只有这两个：它们是**有布局可言**的画面，而 `overview` 的作用正是在挑细节之前
先做一次全局判断，给后面的局部判断上约束。

战斗、菜单、商店的内容全在 `fields` 和 `options` 里，那里的 `overview` 是装饰；
把它也设成必填，只会给一堆和它无关的代码添噪声，而契约里的每一条约束
都应该是有人真的依赖的。
"""



class ScreenState(BaseModel):
    """一帧画面被解析成的结构化状态。

    字段值统一放 `fields` 这个扁平 dict，而不是给每个 scene 定一个子模型：
    机制三的 state key 要从 `(scene, overlay, fields)` 均匀派生，
    分成多个子模型会让 key 的构造对 scene 分支，得不偿失。
    """

    scene: Scene
    overlay: Overlay

    overview: str = Field(
        default="",
        description="一句话描述整幅画面的布局，例如「左下角一栋房子，上方一片草丛，"
        "中间横着一排断崖」。**必须写在 landmarks 之前**——字段的声明顺序就是模型的"
        "输出顺序，先说整体会约束后面挑地标的结果；反过来先挑地标再总结，"
        "总结就只是在复述已经挑错的东西",
    )

    dialog_text: str = Field(
        default="", description="overlay=DIALOG 时框里的文字；其他情况为空"
    )
    options: list[str] = Field(
        default_factory=list,
        description="overlay=CHOICE 时的选项列表。**菜单的区别在这里，不在类型上**",
    )
    cursor: int | None = Field(
        default=None, description="overlay=CHOICE 时光标停在第几项，0 起；未知为 None"
    )
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="该 scene 的结构化字段，键取自 SCENE_FIELDS。读不出的字段直接不放，"
        "**不要填占位值**——分不清'没读到'和'读到了空'会污染状态抽象准确率的标定",
    )
    @model_validator(mode="after")
    def _overview_comes_with_a_layout(self) -> ScreenState:
        """野外和室内必须给 `overview`。

        它不是补充说明，是**看细节之前的那次全局判断**。允许它缺失，模型就会跳过它
        直接去挑地标——而跳过的正是唯一能牵制那些局部判断的东西。
        """
        if self.scene in NEEDS_OVERVIEW and not self.overview.strip():
            raise ValueError(f"scene={self.scene.value} must come with an overview")
        return self

    @field_validator("fields", mode="before")
    @classmethod
    def _stringify(cls, v: object) -> object:
        """把字段值规整成字符串。

        实测：模型会按**语义**给类型——`walkable` 给 `true`（bool），
        `nearby` 给 `["Gramps"]`（list）。它读得完全正确，却因为
        `dict[str, str]` 被整条拒掉。23 帧里有 11 帧栽在这上面，
        而那和感知质量毫无关系。

        判据同 ```json 包裹：**常见格式偏差、语义无歧义，为它判错不划算。**
        `walkable` 是 `true` 还是 `"true"` 是序列化细节。

        为什么不干脆放宽成 `dict[str, Any]`：机制一的 state key 要从 fields 派生，
        值的类型不统一就没法稳定地构造 key。规整在入口做一次，下游永远只见字符串。

        **列表排序后再拼**：模型两次读同一个画面可能给出不同顺序的 `nearby`，
        不排序的话同一个状态会派生出不同的 state key，机制三直接失稳。
        """
        if not isinstance(v, dict):
            return v
        out: dict[str, str] = {}
        for k, val in v.items():
            if isinstance(val, bool):
                out[str(k)] = "true" if val else "false"
            elif isinstance(val, (list, tuple, set)):
                out[str(k)] = ", ".join(sorted(str(x) for x in val))
            elif val is None:
                continue  # 读不出的字段直接不放，不留占位值
            else:
                out[str(k)] = str(val)
        return out

    def available_actions(self) -> tuple[str, ...]:
        """当前可按的键。**只由 overlay 决定**，masking 的数据来源。"""
        return OVERLAY_ACTIONS[self.overlay]

    def expected_fields(self) -> tuple[str, ...]:
        """当前 scene 期望读到的字段名。用于组 prompt 和标定完整度。"""
        return SCENE_FIELDS[self.scene]


# ---- 给测试用的自描述 ----
#
# prompt 里的字段清单和输出样例是**手写在 .md 里的**，因为 prompt 文件必须能被
# 完整读到——打开文件看到 `$scene_fields` 的话，"prompt 可 review"就是句空话。
#
# 漂移由**测试**挡：`test_prompts.py` 拿这里的输出和 .md 的内容对照，
# 给某个 scene 加了字段却忘了改 prompt，测试当场失败。
# 防漂移不需要牺牲可读性，两者用不同手段各自解决。


def describe_scene_fields() -> str:
    """把 SCENE_FIELDS 渲染成 prompt 里的字段清单。"""
    lines = []
    for scene, fields in SCENE_FIELDS.items():
        if fields:
            lines.append(f"- `{scene.value}` → {', '.join(f'`{f}`' for f in fields)}")
        else:
            lines.append(f"- `{scene.value}` → 不需要任何字段，`fields` 留空对象")
    return "\n".join(lines)


EXAMPLES: dict[Scene, ScreenState] = {
    Scene.FIELD: ScreenState(
        scene=Scene.FIELD,
        overlay=Overlay.NONE,
        overview="左上角一片草丛，中上方一栋房子、门开在正下方；"
                 "画面中间横着一排断崖，只在主角正下方有个缺口；下半部是空地，左侧立着一块招牌。",
    ),
    Scene.INDOOR: ScreenState(
        scene=Scene.INDOOR,
        overlay=Overlay.DIALOG,
        overview="一间四面是墙的房间，中间一组柜子，柜子前站着一个人；"
                 "右下方有一处出口。画面下方三行被对话框盖住，看不到地面。",
        dialog_text="OAK: Hello there! Welcome to the world of POKéMON!",
    ),
    Scene.BATTLE: ScreenState(
        scene=Scene.BATTLE,
        overlay=Overlay.CHOICE,
        overview="战斗画面：右上是对手，左下是我方背影，右下角是四选项指令框。",
        options=["FIGHT", "PKMN", "ITEM", "RUN"],
        cursor=0,
        fields={
            "foe_name": "CHARMANDER", "foe_level": "5", "foe_hp": "18/18",
            "my_name": "AL", "my_level": "5", "my_hp": "19/19",
        },
    ),
    Scene.MENU: ScreenState(
        scene=Scene.MENU,
        overlay=Overlay.CHOICE,
        overview="画面右侧弹出一列主菜单条目，光标停在第二项。",
        options=["POKéDEX", "POKéMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT"],
        cursor=1,
        fields={"title": "主菜单"},
    ),
    Scene.SHOP: ScreenState(
        scene=Scene.SHOP,
        overlay=Overlay.CHOICE,
        overview="商店买卖界面：上方是所持金钱，下方是商品与价格的列表。",
        options=["POKé BALL", "POTION", "ANTIDOTE", "CANCEL"],
        cursor=0,
        fields={"money": "3000", "items": "POKé BALL, POTION, ANTIDOTE"},
    ),
    Scene.TRANSITION: ScreenState(
        scene=Scene.TRANSITION,
        overlay=Overlay.NONE,
        overview="画面正在切换，全黑，没有可辨认的内容。",
    ),
}
"""每个 scene 一份合法样例，**同时是 prompt 的内容基准和测试基准**。

为什么每类都要有：只给一份野外样例时，模型在战斗画面上会照着野外那份的形状填——
把地标也照着编出来。样例是模型唯一能看到的"输出长什么样"的实例，
缺哪一类，那一类就靠它自己猜。

三个样例各自还在示范一件容易错的事：

- `indoor` 带对话框：被挡住的三行**全部写 `?`**，不要凭印象补。
  这是 `?` 唯一一个高频用途，不示范的话模型永远不会用它。
- `battle`：`landmarks` 是空的——战斗画面没有格子坐标可言。
- `transition`：**什么都不填**。过场是一帧没有内容的画面，硬填就是编。

prompt 里的样例是手写的（为了文件可读），本模块的这份是基准，
`test_prompts.py` 逐字对照，漂移当场失败。
"""


def json_output_examples() -> dict[Scene, str]:
    """渲染成 prompt 里那几段 JSON。键是 scene，值是格式化好的 JSON 文本。"""
    return {scene: state.model_dump_json(indent=2) for scene, state in EXAMPLES.items()}


def json_output_example() -> str:
    """野外那一份。保留单数形式是因为它是最主要的一类，测试和文档都常单独引用它。"""
    return json_output_examples()[Scene.FIELD]


class ModelCall(BaseModel):
    """一次模型调用留下的账，外加它成没成。

    ## 为什么大脑要把账"交出来"而不是自己记

    **只有 Harness 写 trace。** 大脑是被调用方：它返回结果和账单，
    由 Harness 翻译成事件。上一版不是这样——brain 自己写 MODEL_CALL / THINK /
    ERROR / MEMORY_READ，harness 写 ACT / MEMORY_WRITE / OBSERVE / EPISODE_*，
    于是"某类事件归谁写"要一条条记，还开了个例外（judge 不写 trace，为的是让
    判定器碰不到自己的账）——用例外弥补一条不统一的规则。

    统一之后规则只有一句：**谁控制循环，谁记账。** 判定器碰不到自己的账
    也就不再是特权设计，而是所有大脑调用的共同处境。

    `payload` 直接就是 trace 里 `MODEL_CALL` 的内容。`error_kind` 非空时
    Harness 会**另外补一条 `ERROR` 事件**——账单和失败模式是两件事：
    前者回答"花了多少钱"，后者回答"为什么没拿到东西"，混在一条里两个都统计不出来。
    """

    payload: dict[str, str] = Field(
        default_factory=dict,
        description="token、延迟、prompt 版本、第几次尝试、原始输出。**失败的调用也要有**——"
        "它同样烧了钱，而 `raw` 让你改进解析器之后能离线重算，不必再花 token 重跑",
    )
    error_kind: str = Field(
        default="",
        description="失败类型（ParseFailure / IllegalAction / OutputTruncated…）。"
        "空串表示这次成功了。**单独一列**：聚合失败模式时不必去解析 error 字符串",
    )
    error: str = Field(default="", description="失败详情，一句话")


class Decision(BaseModel):
    """大脑选一次动作的**全部产物**：动作、账单、它翻过哪些记忆。

    `action` 为 None 表示重试全部用尽——**这不是异常，是一类要被统计的失败模式**。
    抛异常的是 Harness（它才知道这一局的死活），大脑只如实汇报。
    """

    action: Action | None = Field(
        default=None, description="选中的动作；None = 重试用尽，一次都没解析出合法动作"
    )
    calls: list[ModelCall] = Field(
        default_factory=list, description="每一次尝试一条，成功失败都在里面，按发生顺序"
    )
    recalled: list[str] = Field(
        default_factory=list,
        description="取回了哪几条记忆，形如 `(episode_id, step)`。"
        "**记引用而不只是条数**——只记数量的话，replay 时无法回答"
        "「这个决策是被哪条经验影响的」，而那正是「记忆到底有没有用」要查的东西",
    )


class Verdict(BaseModel):
    """一次成败判定的结果，连同它花了什么。

    跨层了才做成模型：大脑产出它，Harness 读 `done` 决定要不要终止、
    把 `call` 写进 trace。两边对这三个字段的期待必须是同一份契约。
    """

    done: bool = Field(description="任务达成了没有。**拿不准一律 False**")
    why: str = Field(
        description="看到了什么证据（或为什么证据不足）。"
        "每一个 True 都得说得出依据，否则成功率就是一个无法证伪的数字"
    )
    call: ModelCall = Field(
        default_factory=lambda: ModelCall(),
        description="这次判定的账。判定和决策各自烧 token，分不开就说不清"
        "「成功率这个数字本身花了多少钱」，也算不出判定器自己的失效率——"
        "而**没有失效率的判定器等于没有判定器**",
    )
