"""感知层的数据模型 —— 一帧画面被解析成什么。

**这里的模型不跨到大脑。** 大脑看的是 `core.Observation`；`ScreenState` 是感知层
产出、harness 消费的中间形态。原始画面和这里的细节都不该进 `Observation`。

## 为什么界面类型是二元组而不是扁平枚举

扁平枚举（野外 / 战斗 / 对话框 / 菜单 / 商店 / 过场）在真实画面上立刻自相矛盾：
研究所里弹出对话框，是"室内"还是"对话框"？战斗中弹出对话框，是"战斗"还是"对话框"？
**对话框不是一种场合，是盖在场合上的一层。** 把它和"战斗"并列，等于把"下雨"和"北京"
并列成两种地点。

拆成两个正交维度之后：

- **`overlay` 单独决定可以按什么键**（见 `OVERLAY_ACTIONS`）。三条规则覆盖全部场合；
  扁平枚举下"战斗+对话框""室内+对话框""野外+对话框"要各写一遍同样的掩码。
- **`scene` 单独决定要读哪些字段**（见 `SCENE_FIELDS`）。masking 和状态抽象各取一维，
  互不干扰。
- **菜单内容是数据不是类型。** `FIGHT/ITEM/PKMN/RUN` 和 `TACKLE/GROWL` 都是
  `CHOICE`，区别只在 `options` 的值。扁平枚举会逼你为每个菜单开一个新类型，
  而它们的可用动作完全一样。
- 组合数：扁平是 5×3=15 个类型且只能一个个加；二元组是 5+3=8 个值，组合自动覆盖。
  这对 **append-only** 纪律很要紧——新增一个 scene 不会让已有 overlay 的语义失配，
  机制三的历史 value 也不作废。

## ⚠️ 这个结构是暂定的

用户对它的表态是"先这样吧，暂时没有更好的说法"，**不是认同**。
推翻它的信号（出现任何一个就该重新设计，而不是往里塞特例）：

- 出现"既不是叠加层也不是场合"的第三类东西，只能硬塞进某一维
- 同一个 `overlay` 值在不同 `scene` 下需要不同的动作集（那 `OVERLAY_ACTIONS` 的前提就破了）
- `SCENE_FIELDS` 里开始出现"仅当 overlay=X 时才有意义"的字段（说明两维不正交）

**改之前先看 append-only**：一旦开始积累 `(state-key, action) → value`，
枚举值只能增不能改，否则历史数据全部失配。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Scene(str, Enum):
    """你在什么场合。决定**要读哪些字段**。"""

    FIELD = "field"          # 野外：城镇、路线，可自由走动
    INDOOR = "indoor"        # 室内：研究所、民宅、道馆内部
    BATTLE = "battle"        # 战斗中
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
    Scene.FIELD: ("location", "facing", "walkable", "nearby"),
    Scene.INDOOR: ("place", "facing", "walkable", "nearby"),
    Scene.BATTLE: ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp"),
    Scene.SHOP: ("money", "items"),
    Scene.TRANSITION: (),
}
"""每个场合期望读到哪些字段。

**这是数据不是类型**：给某个 scene 加一个字段，不改变任何枚举值，
所以不触发 append-only 的约束。字段名进 prompt 告诉 VLM 该填什么，
填出来的值进 `ScreenState.fields`。
"""


class ScreenState(BaseModel):
    """一帧画面被解析成的结构化状态。

    字段值统一放 `fields` 这个扁平 dict，而不是给每个 scene 定一个子模型：
    机制三的 state key 要从 `(scene, overlay, fields)` 均匀派生，
    分成多个子模型会让 key 的构造对 scene 分支，得不偿失。
    """

    scene: Scene
    overlay: Overlay

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


def json_output_example() -> str:
    """一份合法的输出样例，作为**测试基准**。

    prompt 里的样例是手写的（为了文件可读），本函数用来验证那份手写的确实合法：
    错的样例比没有样例更糟，模型会照着它学。
    """
    sample = ScreenState(
        scene=Scene.BATTLE,
        overlay=Overlay.CHOICE,
        dialog_text="",
        options=["FIGHT", "PKMN", "ITEM", "RUN"],
        cursor=0,
        fields={"foe_name": "CHARMANDER", "foe_level": "5", "my_name": "AL", "my_hp": "19/19"},
    )
    return sample.model_dump_json(indent=2)
