"""组装好的、按键相关的三个 prompt 常量：`BUTTON_HELP` / `MAP_HINT` / `REPEAT_HINT`。

内容都在 `prompts/*.md` 里，这个文件只做**组装**——`.md` 是纯文本，没法自己
按 `Overlay` 分类、没法自己嵌进当前的地图图例。组装逻辑本身依赖
`schemas.observation`（`Overlay`、`TerrainMap`、`terrain_legend`），放进 `prompts/`
包而不是留在 `game_tools.py`，是因为它产出的是 prompt 内容而不是"大脑的工具"——
`game_tools.py` 只该管"翻译成动作"这一件事，不该同时管"这段说明文字怎么拼出来"。

`game_tools.py` 直接 `from pokemon_agent.prompts.game_hints import BUTTON_HELP, MAP_HINT, REPEAT_HINT`，
拿到的是已经拼好的常量，不用知道它们是从 `.md` 文件读出来的。
"""

from __future__ import annotations

from pokemon_agent.schemas.observation import Overlay, TerrainMap, terrain_legend

from . import load, load_nested_sections

_BUTTON_SECTIONS = load_nested_sections("button_help")
BUTTON_HELP: dict[Overlay, dict[str, str]] = {
    Overlay.NONE: _BUTTON_SECTIONS["none"],
    Overlay.DIALOG: _BUTTON_SECTIONS["dialog"],
    Overlay.CHOICE: _BUTTON_SECTIONS["choice"],
}
"""同一个键在不同 overlay 下含义不同，说明也得跟着变（内容见 `prompts/button_help.md`）。

`a` 在野外是「互动」、在对话框里是「推进」、在选择框里是「确认」——
给大脑一份放之四海的说明，等于让它自己去猜当前语境。

`Overlay` 的三个成员和 `button_help.md` 的三个 `##` 段一一对应，这里只是把
markdown 的分段结果搬进 `dict[Overlay, ...]` 这个类型化的形状。
"""


def _sample_map() -> str:
    """给模型看的读图范例。**由真正的渲染函数生成，不手写。**

    手写的话它迟早和 `TerrainMap.render()` 漂移，而漂移的症状是模型照着一份
    过时的范例去数一张新格式的图——那种错不报错。这和 `terrain_legend()`
    两边共用一份 `TERRAIN_MEANING` 是同一条理由。

    生成给模型看的那份读图范例。
    """
    return TerrainMap(
        cells=["#.....#.GG", "#.....#.GG", "#.....#.GG", "#####N##GG",
               "....@..#GG", "####...#GG", "####...#GG", "#D##...#GG",
               ".......#GG"],
        map_id=0, player_x=15, player_y=2,
    ).render()


MAP_HINT = load("map_hint").render(terrain_legend=terrain_legend(), sample_map=_sample_map())
"""怎么读地图（内容见 `prompts/map_hint.md`）。

这段话的重点从「怎么理解一个可能不准的判断」变成了「怎么用一张准确的地图」——
早先它是视觉模型逐格猜出来的，会错；现在它直接读模拟器内存（`world/ram.py`），
抄的是游戏自己的碰撞判定，**几何这一维从 87% 变成 100%**，而且不要钱、零延迟。

所以这一段最要紧的是把两者的可信度差别讲清楚：`walk_map` 不会错，`landmarks` 会。
不讲清楚的话，模型又会像上一版那样，为了自圆其说去编一个"门是特殊格"出来。

最后一句有来历：更早一版里模型把 `north: grass x3` 当成了**跨步骤的额度**
（"我按过 3 次了，用完了"），在这上面写了 700 token 的自我拉扯。
地图是每帧重出的，这件事必须说明白。
"""

REPEAT_HINT = load("repeat_hint").text
"""连按提示（内容见 `prompts/repeat_hint.md`）。

随动作空间下发而不是写进 prompt 模板，因为它是**动作接口的一部分**——
模型能不能用 `times` 取决于工具层认不认，和 prompt 怎么写无关。

## 为什么要写成规则加例子，而不是只说"可以连按"

实测：模型已经把路径算对了（`(4,4)→left→(3,4)→left→(2,4)→down→(2,5)`），
却仍然只走第一步。它不是不会用 `times`，是**没有理由用**——
"可以连按"是一句许可，许可不会改变行为。

所以这里给的是三样东西：**代价**（每步一次感知调用）、**规则**（把开头同向的一段
合并）、**例子**（left,left,down → `left ×2`）。例子最要紧，它把规则落在
模型自己刚写出来的那种路径上。

反过来，"什么时候不该连按"也要写明（目标是 `?`、预期中途有事件），
否则收紧一处会在另一处过度放开。

**放 `ActionSpace.note` 而不是 `descriptions`**：prompt 只遍历 `names`
渲染说明，塞进 descriptions 的额外键永远不会被渲染出去——写了等于没写。
"""
