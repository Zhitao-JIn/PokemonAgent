"""一帧画面被解析成的结构化状态（world 实现层的私有解析结构）。

**这不是跨层领域实体**：`ScreenState` 只在感知实现内部活一瞬——
视觉模型的文本输出在这里解析成结构化状态，随即拆成 `ObservationFromWorld` 的
`status`/`facts` 标量，从不离开 world 层、从不进 schemas——全项目只有
`pyboy_world.py` 一个文件认识它，所以放 world 层。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from pokemon_agent.schemas.domain import Overlay, Scene

CURSOR_MARKS: frozenset[str] = frozenset("\u25b6\u25ba\u25b8\u27a4>")
"""能当光标的那几个字符：`▶` `►` `▸` `➤` `>`。

只收形状对的，不做模糊匹配——模型在不同帧里写过其中好几个，
为一个字符的差异丢掉整帧读数不划算；但也不能把任意字符都当光标，
否则选项本身以标点开头就会被误判成"被选中"。
"""

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

    dialog_text: str = Field(default="", description="overlay=DIALOG 时框里的文字；其他情况为空")
    options: list[str] = Field(
        default_factory=list,
        description="overlay=CHOICE 时的选项列表。**菜单的区别在这里，不在类型上**。"
        "给了 `option_lines` 时由它派生，视觉模型不必单独再抄一遍",
    )
    option_lines: list[str] = Field(
        default_factory=list,
        description="选项框逐行照抄，**含最左边那个字符**：有光标写 `▶`，没有写空格"
        '（`["▶TACKLE", " GROWL"]`）。`options` 和 `cursor` 都从它派生。'
        "\n\n"
        "**为什么绕这一道：把判断换成转写。** 直接问「光标在哪一项」，"
        "模型要先找到三角、再把它和某个词配对、再说出那个词——是定位加归属判断，"
        "实测经常配错，而配错和配对在输出上一模一样。逐行照抄只要求它回答"
        "「这一行开头有没有三角」，是个局部问题，而三角和选项文字本来就挨着。"
        "\n\n"
        "还白捡两样东西：`options` 不会再被凑成四项（抄几行是几行），"
        "以及**零行或多行带三角时可以判定读错**（见 `_derive_cursor_from_lines`）——"
        "现在读错至少有一半会变成「读不出」，而不是变成一个错的词",
    )
    cursor: str | None = Field(
        default=None,
        description='光标指向那一项的原文（`"RUN"`）；未知为 None。'
        "**给了 `option_lines` 时这个字段由派生结果覆盖**，模型自己填的那份原始值被丢弃。"
        "**不是序号。** 要序号就得让视觉模型数数，而数数正是它最不擅长的一件事——"
        "`facing` 当初从'问模型'改成读内存，就是因为 8/8 全错。抄一个词它只需做一次"
        "视觉配对，不需要计数。而且这样是**可校验的**：不在 `options` 里就是读错了，"
        "当场作废（见 `_cursor_must_be_one_of_the_options`）；填个 `2` 你没有任何办法"
        "知道它对不对",
    )
    fields: dict[str, str] = Field(
        default_factory=dict,
        description="该 scene 的结构化字段。读不出的字段直接不放，"
        "**不要填占位值**——分不清'没读到'和'读到了空'会污染状态抽象准确率的标定",
    )

    @model_validator(mode="after")
    def _derive_cursor_from_lines(self) -> ScreenState:
        """有 `option_lines` 就用它派生 `options` 和 `cursor`。**派生的赢。**

        恰好一行带光标标记才算数：**零行或两行以上一律 `None`**。这是转写换来的
        自校验——"我没看见三角"和"我看见两个三角"都是明确的读不准信号，
        而在旧契约里它们只会表现为一个看着合法的词。

        标记接受几种常见写法：模型在不同帧里写过 `▶` `►` `>`，形状对就行，
        为一个字符的差异丢掉整帧读数不划算。
        """
        if not self.option_lines:
            return self
        marked = [ln for ln in self.option_lines if ln[:1] in CURSOR_MARKS]
        stripped = [
            ln[1:].strip() if ln[:1] in CURSOR_MARKS else ln.strip() for ln in self.option_lines
        ]
        derived = marked[0][1:].strip() if len(marked) == 1 else None
        object.__setattr__(self, "options", [x for x in stripped if x])
        object.__setattr__(self, "cursor", derived)
        return self

    @model_validator(mode="after")
    def _cursor_must_be_one_of_the_options(self) -> ScreenState:
        """光标读出来的词必须是 `options` 里的一项，否则作废成 `None`。

        **这是换成字符串换来的东西**：序号版本没有任何自校验的余地——`cursor=2` 在
        四选项菜单里永远"合法"，读错了也看不出来。词就不一样，对不上就是没读准，
        与其把一个错的词发下去，不如说"不知道"。

        `None` 而不是抛异常：读不出光标是**这一帧的常态**（动画中、光标被挡住），
        不是解析失败。抛异常会让整次感知重跑，代价和收益完全不匹配。
        """
        if self.cursor is not None and self.cursor not in self.options:
            object.__setattr__(self, "cursor", None)
        return self

    @model_validator(mode="after")
    def _overview_comes_with_a_layout(self) -> ScreenState:
        """野外和室内必须给 `overview`。

        它不是补充说明，是**看细节之前的那次全局判断**。允许它缺失，模型就会跳过它
        直接去挑地标——而跳过的正是唯一能牵制那些局部判断的东西。

        校验野外和室内必须给出 overview。
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

        把字段值规整成字符串，容器一律排序。
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
