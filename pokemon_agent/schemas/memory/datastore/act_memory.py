"""单步情景记忆：一条 = 一步。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

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
        """独立的结构化观测快照，由tool层从world观测转换，不依赖world行为。"""

        class Facts(BaseModel):
            """结构化事实快照；冻结旧键和未知额外事实通过extra原样读入。"""

            model_config = ConfigDict(extra="allow")

            class Landmark(BaseModel):
                """同 `Facts.Landmark` 的快照版：门/招牌/人/物/石，只留渲染要用的字段。"""

                kind: str
                map_id: int
                x: int
                y: int

            class BattleStatus(BaseModel):
                """战斗原始字段的独立快照，与 world 类型不互相引用。"""

                class Combatant(BaseModel):
                    name: str
                    level: int
                    hp: int
                    max_hp: int
                    status: str

                mine: Combatant
                foe: Combatant

            scene: str | None = None
            overlay: str | None = None
            facing: str = ""
            landmarks: list[Landmark] = Field(default_factory=list)
            dialog_text: str = ""
            options: list[str] = Field(default_factory=list)
            cursor: str | None = None
            overview: str = ""
            map_id: int | None = None
            screen: str = ""

            neighbor_cells: dict[str, str] = Field(
                default_factory=dict, description="四个方向对应的地形字符"
            )
            cells: list[str] = Field(
                default_factory=list, description="原始地形格；未取得地形时为空"
            )
            option_grid: list[list[str]] = Field(default_factory=list, description="选项的行列排布")
            cursor_cell: tuple[int, int] | None = Field(
                default=None, description="光标所在行列，零起点"
            )
            option_annotations: list[str] = Field(
                default_factory=list, description="逐选项附注原文"
            )
            battle_status: BattleStatus | None = Field(
                default=None, description="战斗双方原始状态框"
            )
            terrain_visible: bool = Field(default=False, description="旧投影是否显示地形图")

            @model_serializer(mode="wrap")
            def serialize_incremental(
                self, handler: SerializerFunctionWrapHandler
            ) -> dict[str, Any]:
                """旧快照未提供的增量字段不进入其序列化结果。"""
                data = handler(self)
                for name in (
                    "neighbor_cells",
                    "cells",
                    "option_grid",
                    "cursor_cell",
                    "option_annotations",
                    "battle_status",
                    "terrain_visible",
                ):
                    if name not in self.model_fields_set:
                        data.pop(name, None)
                return data

            @property
            def scene_value(self) -> str:
                """`scene` 的文本值；`scene` 为 `None` 时给空串。同真身
                `Facts.scene_value`——给只要文本的调用方用（知识检索 query）。"""
                return self.scene or ""

            @property
            def overlay_value(self) -> str:
                """同 `scene_value`，针对 `overlay`。"""
                return self.overlay or ""

        class Place(BaseModel):
            """同 `PlaceInWorld` 的快照版：只留 `map_id`/`x`/`y` 三个原始字段——
            `.step_toward()` 这类行为只有判定层（harness）拿着真身才用得到，
            这里只是存下来的记忆，不需要。"""

            map_id: int
            x: int
            y: int

        step: int = Field(
            description="本局累计键数，从 0 开始（同真身 `world.Observation.step` 口径："
            "局内跨 task 连续；harness 盖章）"
        )
        place: Place | None = Field(default=None, description="主角所在的格子（结构化坐标）")
        scene: str = Field(
            default="", description="task 层的场合（`TaskScene` 的值）；这一字段之前写下的记录为空"
        )
        facts: Facts = Field(default_factory=Facts, description="结构化事实容器的快照")
        done: bool = Field(default=False, description="产生这份观测时世界层是否已经不在了")
        perceived: bool = Field(
            default=True,
            description="仅为读取旧记忆保留的视觉感知标记，不影响当前渲染。",
        )

        observation_flags: list[str] = Field(default_factory=list)

        @model_serializer(mode="wrap")
        def serialize_incremental(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
            """保留旧记忆快照的序列化形状。"""
            data = handler(self)
            if "observation_flags" not in self.model_fields_set:
                data.pop("observation_flags", None)
            return data

    before: Observation = Field(description="做决定时看到的画面")
    action: str = Field(
        description="**一个动作**：键（`up`）或脚本（`script:walk_to(x=5, y=2)`）。"
        "连按已经展开成多步，这里不再是链"
    )
    after: Observation = Field(description="执行之后的画面。**结果也是一次观察**")
    result: str = Field(
        default="",
        description="脚本动作的终态报告摘要（`ok` / `verify_failed` 这类结局码）；键动作为空串。"
        "脚本一次调用占一步、内部 N 键不展开（P5 定案），这个字段就是那一步的机械结局"
        "——判据只认达成的约定下，它是判停可直接采信的证据",
    )
    dialog: list[str] = Field(
        default_factory=list,
        description="脚本调用期间屏幕上依次出现的对话**行**（一行一个元素，不截断）；"
        "键动作为空列表。独立字段而不并进 `result`——`result` 是结局码那一句，"
        "对话是过场原文，两者的读方（判停 / 蒸馏 / 评分）不同。"
        "旧记忆没有这个字段，读作空列表",
    )

    step: int = Field(
        description="该键按下**前**那一帧的本局累计键数（跨 task 连续，harness 盖章）——"
        "相邻记忆构成 `step+1` 链，机制三沿它回填"
    )
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
        "`direct/brain_tool.py::dedup_snapshots()`（0915 起归 tool 层，那是"
        "发请求的组装逻辑，不是记忆的数据形状）",
    )

    # `(episode_id, step)` 就是这条记忆的坐标 —— 一步一条，唯一且语义稳定。
    #
    # 不用 trace 的 `event_id`：那是**记录格式的产物**，取决于这一步之间穿插了
    # 多少别的事件，换个记录粒度就变。`step` 是**轨迹坐标**，而机制三沿轨迹
    # 回填折扣正是按 step 走的——用它，回填时不需要任何转换。
