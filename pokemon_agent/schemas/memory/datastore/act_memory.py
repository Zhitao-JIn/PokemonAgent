"""单步情景记忆：一条 = 一步。"""

from __future__ import annotations

import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SNAPSHOT_BLIND: frozenset[str] = frozenset({"known_objects", "knowledge"})
"""**不进记忆的字段。** 记忆里每一项都必须跨步骤成立，这两项都不成立：

- `known_objects`：跨 episode 的流水，不是"这一帧看到了什么"。
- `knowledge`：语义记忆的检索结果，本来就不是观察。它走
  `ChooseOnceReq.knowledge`（`episode/decide/think_action.py` 从
  `state.knowledge_semantic_memory` 现算文本装进去），不折进
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


class ActMemory(BaseModel):
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
        """`ActMemory` 自己存的"观测快照"——**不是** `pokemon_agent.world.Observation`。

        这条记忆只需要"当时看到的样子"——渲染成文本、跟另一份快照比对是否相同，
        从不需要 `world.Observation`/`Facts` 的任何**行为**（那些是 world 子系统
        对外承诺的 Port 产物）。按"模块间零依赖，只靠裸字段交互"这条边界，这里
        重新声明一份字段形状完全一致、类本身互不引用的内部类型——`ActMemory`
        唯一认识两边形状的组装方是 `brain.brain.py::reflect()`，它负责在构造
        `ActMemory` 之前把真身 `Observation.model_dump(mode="json")` 拍平后
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
    action: str = Field(description="**一个键**，如 `up`。连按已经展开成多步，这里不再是链")
    after: Observation = Field(description="执行之后的画面。**结果也是一次观察**")

    step: int = Field(description="写入时所处的步数")
    episode_id: str = Field(description="这条经验来自哪次尝试")
    task_id: str = Field(default="", description="这条经验属于哪个 task（harness 盖章）")
    run_id: str = Field(
        default="",
        description="这条经验来自哪个 run——checkpoint 恢复的落盘签名三元组之一"
        "（run_id/episode_id/step），由 Harness 盖章（大脑不知道自己在哪个 run）",
    )

    before_frame: str | None = Field(
        default=None,
        description="`before` 对应的截图，**完整的 PNG data URI 字符串**"
        "（`data:image/png;base64,…`，0915 起唯一格式：产出点直接带前缀、"
        "自描述、grep 可寻，裸 base64 已废）。不是文件名，也不是"
        "原始字节。存 data URI 不存文件名引用——**这条记忆的"
        "`before`/`after` 本来就有跟相邻条目重复的问题**（上一条的 after =="
        "下一条的 before），文字字段重复是接受的成本，这条也一并接受：换来的是"
        "`judge`/`verify_steps` 用的时候不用再去读盘、不用再关心截图文件是否"
        "存在/是否被撞名改了后缀——`store_step_episode_memory()` 写这条记忆时"
        "已经从盘上读过一次图、编码好了，后面全是内存里的字符串。"
        "**可能是 `None`**（那一步感知失败、截图确实没能落盘）——调用方"
        "（`judge`/`verify_steps` 拼请求）按跳过这张图处理，不能因为一步缺图"
        "让整条判定链路失败",
    )
    after_frame: str | None = Field(
        default=None,
        description="`after` 对应的截图，格式同 `before_frame`（完整 PNG data URI）。"
        "跟 `before_frame` 之间的关系正是 `render_sequence()`"
        "已经在处理的那种重复——相邻两条 `entries[i].after_frame ==`"
        "`entries[i+1].before_frame`（同一帧画面，编码结果自然相等），拼多模态"
        "请求时应该按这一点去重，不要同一张图发两遍——去重的实现在"
        "`tools/brain_tool.py::dedup_snapshots()`（0915 起归 tool 层，那是"
        "发请求的组装逻辑，不是记忆的数据形状）",
    )

    # `(episode_id, step)` 就是这条记忆的坐标 —— 一步一条，唯一且语义稳定。
    #
    # 不用 trace 的 `event_id`：那是**记录格式的产物**，取决于这一步之间穿插了
    # 多少别的事件，换个记录粒度就变。`step` 是**轨迹坐标**，而机制三沿轨迹
    # 回填折扣正是按 step 走的——用它，回填时不需要任何转换。

    def render(self) -> str:
        """渲染成进 prompt 的样子。**检索打分也用它**——

        两处用同一份文本，是为了让"被选中的内容"和"看到的内容"是同一个东西。
        分成两份的话，可能出现"按 A 的内容选中，却把 B 的内容喂进去"，而且不报错。

        （0923 189 起记忆里没有论据段——JEV 不产出 rationale，这条记录只有
        **发生过的事**：画面、动作、结果。）
        """
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
            f"  做了  {self.action}",
            "  之后变成：\n" + self._render_obs(self.after),
        ]
        return "\n".join(lines)

    @staticmethod
    def _render_obs(obs: ActMemory.Observation) -> str:
        """渲染观测快照，**排除 `walk_map`**——它是坐标推理原料（这一屏哪格能走），
        在记忆的前后对比里几乎不变（同一地图内恒定），每条记忆带两份纯属浪费：
        实测一条记忆 1300 字符，其中 walk_map 占 ~800（before+after 各一份），
        而 judge（3 条历史）/ 审计（整局 8 条）都要渲染它，输入就是这么膨胀的。
        「四邻」（北 G 南 G 西 G 东 G）已给出各方向可通行性，撞墙判断够用，
        不需要整张图。"""
        facts = obs.facts.model_copy(update={"walk_map": ""})
        return obs.model_copy(update={"facts": facts}).render()

    @staticmethod
    def _snapshot_equal(a: ActMemory.Observation, b: ActMemory.Observation) -> bool:
        """忽略 `step` 号之外，两份观测是否完全一致。"""
        return a.model_copy(update={"step": 0}) == b.model_copy(update={"step": 0})


def render_sequence(entries: list[ActMemory]) -> list[str]:
    """把一串 `ActMemory` 逐条渲成 prompt 用的文本，**首尾相接的边界只渲一次**。

    **问题**：`ActMemory.render()` 每条都完整摆 `before`/`after`——但连续两条
    之间，上一条的 `after` 和下一条的 `before` 内容其实完全相同（`store_step_
    episode_memory()` 是同一份 `after_observation` 先当这一条的 `after` 存
    一次，`close_step()` 再把它扶正成下一条的 `before`）。
    校验器喂的是**整局全量**（不像 `judge` 只取最近 `JUDGE_HISTORY_STEPS`
    条——那个常量住 `pokemon_agent/config.py`，这里不重复硬编码），逐条渲染
    就是把每一帧连续存两遍，长局的 prompt 长度直接翻倍。

    **保留全量、只去重渲染**：这里不砍步数（校验器仍然看得到每一步），只在
    相邻两条**确认首尾相接**（`entries[i].step + 1 == entries[i+1].step` 且
    内容一致，用 `_snapshot_equal` 忽略 step 号比较）时，把下一条的"当时看到"
    换成一句指回上一条"之后变成"的提示，不重复贴一遍内容；不连续（比如某步
    因为权限被拒没落库、或调用方本来就传了不连续的子集）时，各自照常完整
    渲染，不猜测省略——这跟 `ActMemory` 本身"每条自成一体、不依赖别的条目
    还在不在"的设计并不冲突：**省的是渲染，不是存储**，条目本身仍然各自完整。

    返回值跟 `entries` 一一对应（长度相同、顺序不变），方便调用方按 index
    各自加编号/包装——`prompts/verify.py` 用来配 `## 第 i 条`，`VerifyVerdict.
    index` 才对得上号；这里不做编号，编号是调用方的事。
    """
    rendered: list[str] = []
    prev: ActMemory | None = None
    for entry in entries:
        if (
            prev is not None
            and prev.step + 1 == entry.step
            and ActMemory._snapshot_equal(prev.after, entry.before)
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
                + ActMemory._render_obs(entry.before)
            )
        lines = [
            before_block,
            f"  做了  {entry.action}",
            "  之后变成：\n" + ActMemory._render_obs(entry.after),
        ]
        rendered.append("\n".join(lines))
        prev = entry
    return rendered
