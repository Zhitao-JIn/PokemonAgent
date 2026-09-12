"""单步情景记忆：一条 = 一步。"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SNAPSHOT_BLIND: frozenset[str] = frozenset({"known_objects", "knowledge"})
"""**不进记忆的字段。** 记忆里每一项都必须跨步骤成立，这两项都不成立：

- `known_objects`：跨 episode 的流水，不是"这一帧看到了什么"。
- `knowledge`：语义记忆的检索结果，本来就不是观察。它走
  `ChooseOnceReq.knowledge`（见 `episode_harness.py`），不折进
  `obs.facts`——这一条留着当双保险，万一哪次改动又把它塞回 `obs.facts`，
  这里还能挡一道，不会静默混进记忆。

（`cursor_said` 从源头上就不写进 `facts`——它不该跨步骤比较，无需在此挡。）

除此之外一律照搬。**这里是排除表而不是白名单**，是有意的：新增一个观测字段时，
默认它应该进记忆，需要理由的是把它挡在外面——反过来的话，加字段的人得记得
回来改清单，而忘了改不报错，只表现为某类画面的变化永远看不见。
"""


def _display_width(text: str) -> int:
    """这段文字占几个字符宽。**中日韩字符算两格。**

    跟 `world.interface.domain.facts._display_width` 是同一份算法——两处都是
    "对齐一段中英混排文本"这一件事，不是彼此依赖的两个模块，各自留一份纯函数
    没有额外代价，换来的是这里不用在类级别 import `pokemon_agent.world`。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


_EXTRA_ORDER: tuple[str, ...] = ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp")
"""同 `world.interface.domain.facts._EXTRA_ORDER`：视觉模型按 scene 自由给的那批
字段里，这几个几乎每帧都出现、值得固定顺序，其余按字母序排在后面。"""

BLIND_NOTE = "（本帧没做视觉感知：场景 / 叠加层 / 对话 / 概况等字段不在这一帧里）"
"""没做过视觉感知的那一帧，渲染时必须顶上的那一行。

**必须显式写出来，不能靠字段为空来暗示。** "没读过"和"读过、是空的/没变"是
两件完全不同的事——静默省略会被读者（大脑、判定器）当成后者。同一条理由见
`world/interface/domain/facts.py` 里"光标读不出要明写"那条。
"""


class StopReason(StrEnum):
    """这一键之后**为什么没有继续按键**。

    记的是**本步的结局**，不是链的状态——链还剩多少，从记忆序列本身看得出
    （后面还有没有记录），不需要写进每一条。

    `None`（不用这个枚举）表示没有异常：要么还有待按的键，要么这一键本来
    就是最后一个。单键链的每一步都是 `None`。
    """

    BLOCKED = "blocked"
    """方向键按下去，位置和朝向都没变、且朝向本来就等于这个方向——原地空转。

    **只有方向键会有这个值**：`a` 不改变位置与朝向，"按了没反应"是它的合法
    结局（对话框本来就没弹），不是撞墙。
    """

    WARP = "warp"
    """`map_id` 变了——这一键把主角送进了另一张地图。

    剩下的键是在**一张没被规划过的地图上**按的，全部作废。
    """

    EPISODE_OVER = "episode_over"
    """本局到此为止——世界没了（模拟器窗口关闭，此时内存读数不再可信），
    或者这一键用掉了最后一步预算。链的剩余部分无从执行。
    """


STOP_NOTE: dict[StopReason, str] = {
    StopReason.BLOCKED: "这个方向上剩下的连按不必再按了（原地不动 = 撞墙）",
    StopReason.WARP: "换到了另一张地图，整条链剩下的键全部作废",
    StopReason.EPISODE_OVER: "本局到此为止，链剩下的键不再执行",
}
"""`stop` 在记忆里渲染成的那句话——**这一键的结局必须让下一步的大脑读得到**。

判据：`stop` 不是决策者自己的说辞，是执行层机械判出来的事实（纯 RAM 比较），
所以它跟着 `做了`/`之后变成` 一起摆，`reason=False` 的那一版（判定器看的
那版）也照摆。

**为什么非写不可**：不写的话，大脑读到的记忆就只是"按了 up、画面没变"，
它会当成"我本来就只打算按一下"——而"链被截了"是它下一步推理的前提
（§5：执行层不许悄悄改写大脑交出来的动作，改了就必须让它知道自己被改了，
`stop` + 落点一起给出，它自己就能推出"在第 3 键撞墙了"）。
"""


class StepMemory(BaseModel):
    """一条情景记忆：**我看到这样的画面，因为这些理由，做了这个动作，然后变成了这样。**

    ## 为什么两头都是完整观察

    只记"结果：你在野外"这种一句话，等于把结果压成一个没有信息量的标签
    （十条全长一个样）。**结果本身也是一次观察**，
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

    class Observation(BaseModel):
        """`StepMemory` 自己存的"观测快照"——**不是** `pokemon_agent.world.Observation`。

        这条记忆只需要"当时看到的样子"——渲染成文本、跟另一份快照比对是否相同，
        从不需要 `world.Observation`/`Facts` 的任何**行为**（那些是 world 子系统
        对外承诺的 Port 产物）。按"模块间零依赖，只靠裸字段交互"这条边界，这里
        重新声明一份字段形状完全一致、类本身互不引用的内部类型——`StepMemory`
        唯一认识两边形状的组装方是 `brain.brain.py::reflect()`，它负责在构造
        `StepMemory` 之前把真身 `Observation.model_dump(mode="json")` 拍平后
        验证成这里的类型（字段名一致，一次 `model_validate()` 就能转过去，不需要
        逐字段手写映射）。
        """

        class Facts(BaseModel):
            """同 `world.interface.domain.facts.Facts` 的快照版：字段、渲染对齐
            算法照抄（两边要渲染出一模一样的文本，大脑才能拿旧记忆和当前观测
            直接比对），但类不互相引用。`extra="allow"`——视觉模型按 scene 自由
            给的字段（`my_hp`/`foe_level`…）原样收进来，同真身一致。
            """

            model_config = ConfigDict(extra="allow")

            class Landmark(BaseModel):
                """同 `Facts.Landmark` 的快照版：门/招牌/人/物/石，只留渲染要用的字段。"""

                kind: str
                map_id: int
                x: int
                y: int

                def render(self) -> str:
                    return f"{self.kind} x={self.x} y={self.y}"

            scene: str | None = None
            overlay: str | None = None
            where: str = ""
            facing: str = ""
            neighbors: str = ""
            landmarks: list[Landmark] = Field(default_factory=list)
            dialog_text: str = ""
            options: list[str] = Field(default_factory=list)
            cursor: str | None = None
            overview: str = ""
            walk_map: str = ""
            map_id: int | None = None

            @property
            def scene_value(self) -> str:
                """`scene` 的文本值；`scene` 为 `None` 时给空串。同真身
                `Facts.scene_value`——给只要文本的调用方用（知识检索 query）。"""
                return self.scene or ""

            @property
            def overlay_value(self) -> str:
                """同 `scene_value`，针对 `overlay`。"""
                return self.overlay or ""

            def _entries(self) -> list[tuple[str, str, str]]:
                """`(字段名, 中文标签, 文本)` 列表，只含"有值"的字段，按固定顺序。
                同真身 `Facts._entries()`——顺序必须一致，两边渲染出的文本才能
                让大脑逐行对照。
                """
                entries: list[tuple[str, str, str]] = []
                if self.scene is not None:
                    entries.append(("scene", "场景", self.scene))
                if self.overlay is not None:
                    entries.append(("overlay", "叠加层", self.overlay))
                if self.where:
                    entries.append(("where", "位置", self.where))
                if self.map_id is not None:
                    entries.append(("map_id", "地图", str(self.map_id)))
                if self.facing:
                    entries.append(("facing", "朝向", self.facing))
                if self.neighbors:
                    entries.append(("neighbors", "四邻", self.neighbors))
                if self.landmarks:
                    entries.append(
                        ("landmarks", "地标", "; ".join(m.render() for m in self.landmarks))
                    )
                if self.dialog_text:
                    entries.append(("dialog_text", "对话", self.dialog_text))
                if self.options:
                    entries.append(("options", "选项", " / ".join(self.options)))
                if self.cursor:
                    entries.append(("cursor", "光标", self.cursor))
                extra: dict[str, Any] = self.model_extra or {}
                seen = set()
                for k in _EXTRA_ORDER:
                    if k in extra and extra[k] not in (None, ""):
                        entries.append((k, k, str(extra[k])))
                        seen.add(k)
                for k in sorted(extra):
                    if k in seen or extra[k] in (None, ""):
                        continue
                    entries.append((k, k, str(extra[k])))
                if self.overview:
                    entries.append(("overview", "概况", self.overview))
                if self.walk_map:
                    entries.append(("walk_map", "walk_map", self.walk_map))
                return entries

            def render(self, indent: str = "  ") -> str:
                """把这份 facts 渲染成一段可读、可打分的文本。同真身 `Facts.render()`。"""
                entries = self._entries()
                if not entries:
                    return ""
                width = max(_display_width(label) for _k, label, _v in entries)
                lines = []
                for _k, label, body in entries:
                    pad = " " * (width - _display_width(label) + 2)
                    gutter = " " * (len(indent) + width + 2)
                    body = body.replace("\n", "\n" + gutter)
                    lines.append(f"{indent}{label}{pad}{body}")
                return "\n".join(lines)

        class Place(BaseModel):
            """同 `PlaceInWorld` 的快照版：只留 `map_id`/`x`/`y` 三个原始字段——
            `.step_toward()` 这类行为只有判定层（harness）拿着真身才用得到，
            这里只是存下来的记忆，不需要。"""

            map_id: int
            x: int
            y: int

        step: int = Field(description="本 episode 内的第几步，从 0 开始")
        place: Place | None = Field(default=None, description="主角所在的格子（结构化坐标）")
        status: str = Field(description="这一帧的状态行")
        facts: Facts = Field(default_factory=Facts, description="结构化事实容器的快照")
        done: bool = Field(default=False, description="产生这份观测时世界层是否已经不在了")
        perceived: bool = Field(
            default=True,
            description="这一帧做过视觉感知没有。**链内按键只做纯 RAM 观测**——"
            "位置/朝向/地标/通行图免费且确定，而视觉模型一次调用只买得到场景与对话。"
            "所以那些帧的 `perceived` 是 False：`scene`/`overlay`/`dialog_text`/"
            "`overview` **不是空的，是没读过**。这两者必须能分开——"
            "静默省略会被读成「这些字段没变」",
        )

        def render(self, indent: str = "  ") -> str:
            """同真身 `Observation.render()`；**没做过视觉感知时显式顶一行**。"""
            body = self.facts.render(indent)
            text = body if body else f"{indent}{self.status}"
            return text if self.perceived else f"{indent}{BLIND_NOTE}\n{text}"

    before: Observation = Field(description="做决定时看到的画面")
    rationale: list[str] = Field(
        description="**这一步所属那一小段**的论据。不是完整推理——那留在 trace 里；"
        "也不是整条链的理由——链级的「为什么要交出这串动作」对其中任何一个键都不成立，"
        "所以它归 `thought`（只进 trace）。这里落的是 `ActionSegmentFromBrain.rationale`"
    )
    action: str = Field(description="**一个键**，如 `up`。连按已经展开成多步，这里不再是链")
    stop: StopReason | None = Field(
        default=None,
        description="这一键之后为什么没有继续按键（`None` = 没有异常）。"
        "**是本步的结局，不是链的状态**——链还剩多少，从记忆序列本身看得出，"
        "不需要重复写进每一条",
    )
    after: Observation = Field(description="执行之后的画面。**结果也是一次观察**")

    step: int = Field(description="写入时所处的步数")
    plan_step_start: int | None = Field(
        default=None,
        description="**这一键属于哪一次决策**——那次决策落在第几步。"
        "`None` = 按 `step` 算（这一键自成一链），**老记录天然正确**：粒度下沉之前"
        "一步就是一次决策，两者本来就相等。"
        "**它不是链字段**：`chain_index`/`chain_length` 的读者问的是"
        "「这条链长什么样」，它的读者问的是「这一步是哪次决策按的」——判据见 "
        "`docs/spec/harness/PLAN_action_step_granularity.md` §4/§11。"
        "唯一用途是**按决策分组**（给大脑看的 `render_decisions()`、给判定器取窗的 "
        "`last_decisions()`），存储与检索都不依赖它；`state` 那份由 `think_action` 设、"
        "`store_step_episode_memory` 抄进来",
    )
    episode_id: str = Field(description="这条经验来自哪次尝试")
    run_id: str = Field(
        default="",
        description="这条经验来自哪个 run——checkpoint 恢复的落盘签名三元组之一"
        "（run_id/episode_id/step），由 Harness 盖章（大脑不知道自己在哪个 run）",
    )

    before_frame: str | None = Field(
        default=None,
        description="`before` 对应的截图，**base64 编码后的 PNG 字符串**——"
        "直接是 VLM REST API `image_url` 要拼的那个格式"
        '（`f"data:image/png;base64,{before_frame}"`），不是文件名，也不是'
        "原始字节。存 base64 不存文件名引用——**这条记忆的"
        "`before`/`after` 本来就有跟相邻条目重复的问题**（上一条的 after =="
        "下一条的 before），文字字段重复是接受的成本，这条也一并接受：换来的是"
        "`judge`/`verify_steps` 用的时候不用再去读盘、不用再关心截图文件是否"
        "存在/是否被撞名改了后缀——`store_step_episode_memory()` 写这条记忆时"
        "已经从 `trace_data/<run_id>/screenshot/` 读过一次盘、编码好了，后面全是内存里的字符串。"
        "**可能是 `None`**（那一步感知失败、截图确实没能落盘）——调用方"
        "（`judge`/`verify_steps` 拼请求）按跳过这张图处理，不能因为一步缺图"
        "让整条判定链路失败",
    )
    after_frame: str | None = Field(
        default=None,
        description="`after` 对应的截图，格式同 `before_frame`（base64 编码的"
        "PNG 字符串）。跟 `before_frame` 之间的关系正是 `render_sequence()`"
        "已经在处理的那种重复——相邻两条 `entries[i].after_frame ==`"
        "`entries[i+1].before_frame`（同一帧画面，编码结果自然相等），拼多模态"
        "请求时应该按这一点去重，不要同一张图发两遍，见 `dedup_snapshots()`",
    )

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
        # 红线：不做“前后一样就折叠成一句「什么都没变」”的折叠——“这一帧
        # 真正会变的字段”清单不可能手工穷举，折叠依据的字段在战斗帧恒等，
        # 会把“这个动作没有效果”的错误结论喂给大脑，而错误的结论比没有
        # 结论贵得多。只摆事实：两份快照字段对齐、顺序固定，变没变由它
        # 自己读。防不去对比的那条，改在决策 prompt 里说（`decide.md`）。
        lines = [
            f"({self.episode_id}, step={self.step}) 当时看到：",
            self._render_obs(self.before),
        ]
        if reason:
            lines.append(f"  因为  {because}")
        lines += [f"  做了  {self.action}", "  之后变成：\n" + self._render_obs(self.after)]
        # `stop` **不受 `reason` 约束**：它是执行层机械判出来的事实，不是
        # 决策者自己的说辞（见 `STOP_NOTE`）。
        if self.stop is not None:
            lines.append(f"  然后停了  {STOP_NOTE[self.stop]}")
        return "\n".join(lines)

    @staticmethod
    def _render_obs(obs: StepMemory.Observation) -> str:
        """渲染观测快照，**排除 `walk_map`**——它是坐标推理原料（这一屏哪格能走），
        在记忆的前后对比里几乎不变（同一地图内恒定），每条记忆带两份纯属浪费：
        实测一条记忆 1300 字符，其中 walk_map 占 ~800（before+after 各一份），
        而 judge（3 条历史）/ 审计（整局 8 条）都要渲染它，输入就是这么膨胀的。
        「四邻」（北 G 南 G 西 G 东 G）已给出各方向可通行性，撞墙判断够用，
        不需要整张图。"""
        facts = obs.facts.model_copy(update={"walk_map": ""})
        return obs.model_copy(update={"facts": facts}).render()

    @staticmethod
    def _snapshot_equal(a: StepMemory.Observation, b: StepMemory.Observation) -> bool:
        """忽略 `step` 号之外，两份观测是否完全一致。"""
        return a.model_copy(update={"step": 0}) == b.model_copy(update={"step": 0})


def render_sequence(entries: list[StepMemory], *, reason: bool = True) -> list[str]:
    """把一串 `StepMemory` 逐条渲成 prompt 用的文本，**首尾相接的边界只渲一次**。

    **问题**：`StepMemory.render()` 每条都完整摆 `before`/`after`——但连续两条
    之间，上一条的 `after` 和下一条的 `before` 内容其实完全相同（`store_step_
    episode_memory()` 是同一份 `pending_observation` 先当这一条的 `after` 存
    一次，`close_step()` 再把它扶正成下一条的 `before`）。
    校验器喂的是**整局全量**（不像 `judge` 只取 `JUDGE_HISTORY` 条——具体
    数字见 `episode_harness.py` 里的定义，这里不重复硬编码），逐条渲染就是把
    每一帧连续存两遍，长局的 prompt 长度直接翻倍。

    **保留全量、只去重渲染**：这里不砍步数（校验器仍然看得到每一步），只在
    相邻两条**确认首尾相接**（`entries[i].step + 1 == entries[i+1].step` 且
    内容一致，用 `_snapshot_equal` 忽略 step 号比较）时，把下一条的"当时看到"
    换成一句指回上一条"之后变成"的提示，不重复贴一遍内容；不连续（比如某步
    因为权限被拒没落库、或调用方本来就传了不连续的子集）时，各自照常完整
    渲染，不猜测省略——这跟 `StepMemory` 本身"每条自成一体、不依赖别的条目
    还在不在"的设计并不冲突：**省的是渲染，不是存储**，条目本身仍然各自完整。

    返回值跟 `entries` 一一对应（长度相同、顺序不变），方便调用方按 index
    各自加编号/包装——`step_verify.py` 用来配 `## 第 i 条`，`StepVerifyVerdict.
    index` 才对得上号；这里不做编号，编号是调用方的事。
    """
    rendered: list[str] = []
    prev: StepMemory | None = None
    for entry in entries:
        because = "；".join(entry.rationale) or "（未给出理由）"
        if (
            prev is not None
            and prev.step + 1 == entry.step
            and StepMemory._snapshot_equal(prev.after, entry.before)
        ):
            # 去重只省画面内容，**条目头必须保留**：头里的 step 号是判定器
            # 执行"看到 step=N 就停"这类步数判据的唯一依据——整段替换掉
            # 的话，窗口里最后一条（恰恰是判停要看的那个步号）在 prompt 里
            # 没有数字，判据永远等不到信号（0909 维度 1 卡 step 3 的事故）。
            before_block = (
                f"({entry.episode_id}, step={entry.step}) 当时看到："
                "（同上一条「之后变成」，同一帧，不重复贴）"
            )
        else:
            before_block = (
                f"({entry.episode_id}, step={entry.step}) 当时看到：\n"
                + StepMemory._render_obs(entry.before)
            )
        lines = [before_block]
        if reason:
            lines.append(f"  因为  {because}")
        lines += [
            f"  做了  {entry.action}",
            "  之后变成：\n" + StepMemory._render_obs(entry.after),
        ]
        # 同 `StepMemory.render()`：`stop` 是机械事实，不看 `reason`。
        if entry.stop is not None:
            lines.append(f"  然后停了  {STOP_NOTE[entry.stop]}")
        rendered.append("\n".join(lines))
        prev = entry
    return rendered


def decision_key(entry: StepMemory) -> int:
    """这条记忆属于**哪一次决策**——标识就是那次决策落在第几步。

    `plan_step_start` 为空（粒度下沉之前写的老记录）时退化成 `step`——那时候
    一步就是一次决策，一条记忆自成一个决策组，**那正是当时的事实**。
    """
    return entry.step if entry.plan_step_start is None else entry.plan_step_start


def group_by_decision(entries: list[StepMemory]) -> list[list[StepMemory]]:
    """把**按步号升序**的一串记忆按决策切开：同一次决策的键连续成组，顺序不变。

    **切组只看决策标识是否与上一条相同**（`decision_key`），不重排、不补洞：一次决策
    中间缺了一步（那一步因为权限被拒之类没落库）仍然算同一次决策——**缺的是记录，
    不是归属**；只有标识本身变了才切。标识相同却不相邻的两段（同一局里回不到同一次
    决策，实际不会出现）也会各自成组，因为上一条的标识不同。
    这跟 `render_sequence()`「不连续就各自完整渲染、不猜测省略」是同一条纪律：
    **宁可少合并，也不猜。**
    """
    groups: list[list[StepMemory]] = []
    for entry in entries:
        if groups and decision_key(groups[-1][-1]) == decision_key(entry):
            groups[-1].append(entry)
        else:
            groups.append([entry])
    return groups


def last_decisions(entries: list[StepMemory], count: int) -> list[StepMemory]:
    """取**最近 `count` 次决策**的全部键（保持原来的升序）。

    **为什么需要它**：记忆的检索面只认步号（`limit` 是"几条记忆"），而判定器要的是
    "最近几次决策"。粒度下沉到单键之后两者不再等价（一次决策能按 8 个键），所以
    取回来还要按决策裁一刀——裁掉的**整次**去掉，不把某次决策砍成半截：半截里
    "这一键之后为什么停"是读不出来的。

    `entries` 不够 `count` 次决策时，有几次给几次（不补、不报错）。
    """
    assert count > 0, f"last_decisions() count must be > 0, got {count}"
    groups = group_by_decision(entries)
    return [entry for group in groups[-count:] for entry in group]


def render_decisions(entries: list[StepMemory], *, reason: bool = True) -> list[str]:
    """按**决策**把本局走过的事渲成 prompt 文本：一次决策一段，返回与决策一一对应的列表。

    **它渲的不是每条记忆，是每次决策。** `render_sequence()` 是逐条（一键一条、
    带相邻帧去重），那是给拿证据的判定器/校验器看的；给**决策者**看的那一版要按
    决策合并——它决策时的粒度就是一次决策（写 `up×4 -> down×2`），回看时也该是
    "这一次按了哪几个键、在哪一脚下停的、最后落在哪"。

    **为什么必须合并（实测）**：一条记忆渲成文本约 490 字符，而本局的**全部**步骤
    都要进决策 prompt（`retrieve_step_episode_memory` 是全量）。粒度下沉到单键之后，
    同一次决策的每个键各占一段——2026-09-11 实测决策 prompt 里「相关记忆」一节已占
    6.8%（971 / 14316 字符），而它按决策长度线性放大（一次决策按 4 个键就是 4 倍）。
    合并之后一次决策只留**两端两帧**（第一次「当时看到」与最后一次「之后变成」）；中间帧的
    内容一条不删地留在记忆里，判定/校验/审计那条路（`render_sequence()`）照旧全看得到。

    **中间帧不是"从它眼里拿掉"的**：粒度下沉之前一次决策只感知一次、只留两端两帧，
    链内中间帧**从来不存在**。合并渲染给决策者的信息量就是恢复到那个水平，**多给的
    是每个键的动作、步号与结局**（`stop`）以及每一段的理由。

    去重规则跟 `render_sequence()` 同一条：上一次决策的「之后变成」与这一次决策的「当时看到」
    本来就是同一帧（`close_step()` 扶正的就是它）时，换成一句指回去的提示。

    `reason=False` 去掉「因为」那一行，只留发生过的事；某个键开始换段时打一次
    （同一段里的键共享理由。两段理由写得一模一样时第二次不重复打——丢掉的是重复文本）。
    """
    rendered: list[str] = []
    prev_tail: StepMemory | None = None
    for group in group_by_decision(entries):
        head, tail = group[0], group[-1]
        span = f"step={head.step}" if head is tail else f"step={head.step}..{tail.step}"
        lines = [f"({head.episode_id}, {span}) 一次决策按的 {len(group)} 个键："]
        if (
            prev_tail is not None
            and prev_tail.step + 1 == head.step
            and StepMemory._snapshot_equal(prev_tail.after, head.before)
        ):
            lines.append("  当时看到：（同上一条「之后变成」，同一帧，不重复贴）")
        else:
            lines.append("  当时看到：\n" + StepMemory._render_obs(head.before))
        shown: list[str] | None = None
        for entry in group:
            if reason and entry.rationale != shown:
                lines.append(f"  因为  {'；'.join(entry.rationale) or '（未给出理由）'}")
            shown = entry.rationale
            line = f"  按了  {entry.action}（第 {entry.step} 步）"
            if entry.stop is not None:
                line += f"  然后停了  {STOP_NOTE[entry.stop]}"
            lines.append(line)
        lines.append("  之后变成：\n" + StepMemory._render_obs(tail.after))
        rendered.append("\n".join(lines))
        prev_tail = tail
    return rendered


def dedup_snapshots(
    entries: list[StepMemory],
) -> tuple[list[str], list[StepMemory.Observation]]:
    """把一串 `StepMemory` 摊平成 `(before, after, before, after, ...)` 的观测
    序列，去重后**一次遍历、一口气**返回两条严格对齐的列表：截图（base64
    字符串，喂 `VisionDescribeReq.images`）和它们各自对应的 `StepMemory.
    Observation` 快照（给调用方转文字，比如"当前观测"要渲成 `$observation`）。
    **两条列表长度、顺序永远一一对应**——`frames[i]` 就是 `snapshots[i]`
    这份观测的那张截图。

    两条列表由构造保证一一对应，调用方不必自己论证“这个索引对应那份观测”
    （靠“最后一条的 after 就是当前观测”去猜索引，只在 history 非空且连续时
    成立，猜错了没人报错、只是悄悄喂错内容）。不需要 `snapshots` 的调用方
    用 `_` 丢弃第二个返回值。

    去重规则不变（跟 `render_sequence()` 是同一件事的图片版）：相邻两条之间
    `entries[i].after_frame` 和 `entries[i+1].before_frame` 本来就是同一帧
    画面（`store_step_episode_memory()` 是同一份观测先存成上一条的 after，
    `close_step()` 再把它扶正成下一条的 before，编码结果自然相等），
    图片不该重复发一遍——每多发一张图，多模态请求就多花一份 token。去重只看
    **字符串是否等于上一张已经收进来的**：同一帧画面编出来的 base64 永远
    逐字节相等，不会出现"内容相同但字符串不同"需要额外判断的情况；反过来，
    不连续的两条（比如中间有一步权限被拒没能落库）编码结果天然不同，不会
    被误判成重复。

    **没有截图的观测不进这两条列表**（`before_frame`/`after_frame` 为
    `None`，比如那一步感知失败没能落盘）——它们既进不了图片列表，就没有
    "这张图对应哪份观测"这件事，两条列表必须永远等长，宁可这份观测彻底不
    出现，也不能让长度对不上。
    """
    frames: list[str] = []
    snapshots: list[StepMemory.Observation] = []
    for entry in entries:
        for obs, frame in ((entry.before, entry.before_frame), (entry.after, entry.after_frame)):
            if frame is None:
                continue
            if frames and frames[-1] == frame:
                continue
            frames.append(frame)
            snapshots.append(obs)
    return frames, snapshots
