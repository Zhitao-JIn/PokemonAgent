"""`decide_action.md` 一个模板的**全部**装配逻辑——加载、拼装、渲染、重试，
都在这一个文件里，对外只暴露两类东西：

- **常量** `BUTTON_HELP`/`MAP_HINT`/`REPEAT_HINT`：给 `game_tools.py` 构造
  `ActionSpace` 用（按当前 overlay 选按键说明、挂地图/连按提示）。
- **函数** `build_prompt(req: FromHarnessToBrainToolChooseOnceReq)`/
  `retry_prompt(req: RetryPromptReq)`：给调用方（`BrainTool`）用，
  各自对应一次决策请求的"首次组装"和"重试追加"，**都只收一个 req 参数**
  ——`build_prompt` 收 harness 信封（素材在那里才拿得到），`retry_prompt`
  用本文件自己的 `RetryPromptReq`。

**这是这次拆分要解决的问题**：之前这四份东西的组装逻辑分散在三处——
`game_hints.py`（前三个常量）、`brain_hints.py`（`retry_note()`）、
`Brain._build_prompt()`/`Brain.retry_prompt()`（最终拼装）——`Brain` 既要 import
两个 prompts 子模块、又要自己做最后一道拼装，读代码得跳三个文件才拼得出
"decide_action.md 最终长什么样"这件事的全貌。现在收进一个文件：`Brain` 只调
两个函数，不再关心 `$facts`/`$actions` 这些占位符怎么填的细节，那是这个文件
自己的事。

四份内容文件（`decide_action.md` 本体 + 三个复用片段 + `retry_note.md`）都在
同目录的 `calls/decide_action/` 里，`load(name)` 会自动找到，不用管相对路径。
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.brain import Goal
from pokemon_agent.config import MAX_RATIONALE, MAX_SEGMENTS
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq
from pokemon_agent.schemas.memory import render_decisions
from pokemon_agent.world import terrain_legend
from pokemon_agent.world.interface import Facts

from . import load, load_nested_sections

# ---- 按 overlay 分流的按键说明（给 game_tools.py 构造动作空间用）----

_BUTTON_SECTIONS = load_nested_sections("button_help")
BUTTON_HELP: dict[Facts.Overlay, dict[str, str]] = {
    Facts.Overlay.NONE: _BUTTON_SECTIONS["none"],
    Facts.Overlay.DIALOG: _BUTTON_SECTIONS["dialog"],
    Facts.Overlay.CHOICE: _BUTTON_SECTIONS["choice"],
}
"""同一个键在不同 overlay 下含义不同，说明也得跟着变（内容见
`calls/decide_action/button_help.md`）。

`a` 在野外是「互动」、在对话框里是「推进」、在选择框里是「确认」——
给大脑一份放之四海的说明，等于让它自己去猜当前语境。

`Facts.Overlay` 的三个成员和 `button_help.md` 的三个 `##` 段一一对应，这里只是把
markdown 的分段结果搬进 `dict[Facts.Overlay, ...]` 这个类型化的形状。
"""


def _sample_map() -> str:
    """给模型看的读图范例（手写内联，按 `TerrainMap.render()` 的格式）。

    `render()` 的行列号是拿 `player_x/player_y` 换算出来的，手写这份时
    已经按范例的参数（`map_id=0, player_x=15, player_y=2`）换算好写死。
    将来改了网格尺寸或坐标写法，这里要跟着改——prompt 文件必须能被完整读到，
    内联正是为了这一点。

    **开头声明句不写具体数字，数字只出现在每行行尾的括号里**——2026-09-08
    实测发现模型会把范例里的坐标声明当成通用规则套到当前帧上（范例 x=11..20、
    当前帧 x=9..18，两份声明在同一份 prompt 里并存），算出矛盾后开始长篇
    自我核对。改成行尾括号后，每行自带权威范围，范例与数据同构，无从混淆。

    给模型看的那份读图范例。
    """
    return (
        "这一屏 10 列 × 9 行；每行末尾括号里是该行首尾两格的全局 x\n"
        "y=-2 #.....#.GG  (x=11..20)\n"
        "y=-1 #.....#.GG  (x=11..20)\n"
        "y=0  #.....#.GG  (x=11..20)\n"
        "y=1  #####N##GG  (x=11..20)\n"
        "y=2  ....@..#GG  (x=11..20)\n"
        "y=3  ####...#GG  (x=11..20)\n"
        "y=4  ####...#GG  (x=11..20)\n"
        "y=5  #D##...#GG  (x=11..20)\n"
        "y=6  .......#GG  (x=11..20)"
    )


MAP_HINT = load("map_hint").render(terrain_legend=terrain_legend(), sample_map=_sample_map())
"""怎么读地图（内容见 `calls/decide_action/map_hint.md`）。

这段话的重点是「怎么用一张准确的地图」：`walk_map` 直接读模拟器内存
（`world/ram.py`），抄的是游戏自己的碰撞判定，**几何这一维是 100%**，
而且不要钱、零延迟。

所以这一段最要紧的是把两者的可信度差别讲清楚：`walk_map` 不会错，`landmarks` 会。
不讲清楚的话，模型会为了自圆其说去编一个"门是特殊格"出来。

最后一句是红线：模型会把 `north: grass x3` 当成**跨步骤的额度**
（"我按过 3 次了，用完了"），在这上面自我拉扯。
地图是每帧重出的，这件事必须说明白。
"""

REPEAT_HINT = load("repeat_hint").text
"""连按提示（内容见 `calls/decide_action/repeat_hint.md`）。

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

# ---- decide_action.md 本体：加载 + 拼装 + 渲染（给 Brain 用）----

_TEMPLATE = load("decide_action")
_HUMAN_NOTE_TEMPLATE = load("human_note")


def _render_goals(goals: list[Goal]) -> str:
    """把目标栈画出来，栈顶在最上面——模型是从上往下读 prompt 的。"""
    lines = []
    for depth, g in reversed(list(enumerate(goals))):
        mark = "← 你现在要完成的" if depth == len(goals) - 1 else ""
        role = "任务目标" if depth == 0 else f"子目标（第 {depth} 层）"
        lines.append(f"{depth}. [{role}] {g.goal}\n   判据：{g.criteria} {mark}".rstrip())
    return "\n".join(lines)


def _render_human_note(note: str) -> str:
    """把这一步的人类实时插话（`RunDataCenter` 的 human_note 槽，取一次即清空）
    渲染成一个独立小节。**空串时不留痕迹**——没人插话是常态，硬塞一句
    "这一步没有人插话"每步都要发一遍，纯噪音；具体这段小节怎么措辞、为什么要
    写"最高优先级"压过其余规则，全部在 `human_note.md` 里（跟 `retry_note.md`
    同一种模式），这里只做"空则不渲染"这一件事（理由见
    `pokemon_agent/prompts/__init__.py` 模块 docstring：prompt
    渲染的内容问题都交给 prompt 文件，Python 只管数据和简单的开关逻辑）。
    """
    if not note:
        return ""
    return _HUMAN_NOTE_TEMPLATE.render(note=note)


def build_prompt(req: FromHarnessToBrainToolChooseOnceReq) -> str:
    """组装一次决策请求对应的完整 `decide_action.md`。**只组装一次**——重试
    追加纠正说明是 `retry_prompt()` 的事，不会重新调用这里（同一份基础
    prompt 前缀，多次重试尝试才能共享缓存，见 `retry_prompt()`）。

    **收 harness 信封而不是 brain 的原生 `ChooseOnceReq`**：观测、动作空间、
    记忆这些素材只有 harness 侧才拿得到（brain 的契约里它们已经被渲染成
    文本或拆成裸字段了）。渲染完的字符串由 `brain_tool` 装进
    `ChooseOnceReq` 交给大脑——**prompt 组装与"进 brain 那最后一跳"都在
    tool 层，转换点唯一**。

    **调用方是 `BrainTool.choose()`**（0913 定案）：信封里**没有 `prompt` 字段**
    ——本函数是"素材 → 文本"的转换，产物是局部变量，不再回填进 req
    （那个中间态曾经外露成 `req.model_copy(update={"prompt": ...})`，
    而 harness 与 tool 两处都要碰 prompt）。

    前置条件：`req.space.names` 非空、`req.goals` 非空、`req.obs.done` 为
    False——这里自己 assert，不依赖调用方先检查过：这是 decide_action.md
    拼装的唯一入口，谁调用都要满足同一组前提。

    `facts` 只装 `req.obs.facts` 里的东西——调用方（`EpisodeHarness.think_action`）
    负责不把 `knowledge`/`episode_memories` 塞进 `obs.facts`，这里不做过滤，
    只信任这个前置条件。`knowledge`/`episode_memories` 走各自的占位符，
    跟 `memories` 一样分开渲染、分开给可信度说明。

    `memories` 那一段**按决策合并**（`render_decisions()`）：一次决策一段，只摆两端两帧
    ——决策者当时就是按串键想的，回看也该是那个粒度；逐条渲染的版本（带相邻帧去重）
    留给拿证据的判定器/校验器。

    拼出这一步的完整 prompt。
    """
    goals, obs, space = req.goals, req.obs, req.space
    assert space.names, "build_prompt() got an empty action space"
    assert not obs.done, "build_prompt() called on a finished episode"
    assert goals, "build_prompt() got an empty goal stack"
    facts = "\n".join(f"- {k}: {v}" for k, v in obs.facts.items()) or "（无）"
    # **按决策合并渲染**（不是逐条 `render()`）：`req.memories` 是本局全量、一键一条，
    # 逐条渲会让同一次决策的中间帧各占一段，按决策长度线性放大决策 prompt。理由与实测见
    # `schemas/memory/datastore/step_memory.py::render_decisions()`。
    recalled = "\n\n".join(render_decisions(req.memories)) or "（无相关记忆）"
    human_note_block = _render_human_note(req.human_note)
    actions = "\n".join(
        f"- {name}: {space.descriptions.get(name, '（无说明）')}" for name in space.names
    )
    if space.note:
        actions += f"\n\n{space.note}"
    return _TEMPLATE.render(
        goals=_render_goals(goals),
        status=obs.status,
        facts=facts,
        # 模板里 $map_guide 在静态说明区（$goals 之前），不在 $facts 后面——
        # 2026-09-08 重排：静态说明全部前移进 prompt 前缀（命中上下文缓存），
        # 动态数据（goals/facts/knowledge/memories/…）集中靠后。旧安排
        # （map_guide 挨着 facts，"规则贴着数据读"）的收益被行尾 x 范围
        # （数据自解释，见 `world/ram.py` 的 `render()`）替代：模型不再需要
        # 读完一大段规则才知道括号是什么，数据自己带着说明。
        map_guide=space.map_note,
        knowledge=req.knowledge or "（没有检索到相关知识）",
        memories=recalled,
        episode_memories=req.episode_memories or "（无跨局摘要）",
        actions=actions,
        max_rationale=MAX_RATIONALE,
        max_segments=MAX_SEGMENTS,
        human_note_block=human_note_block,
    )


# ---- 重试追加（给 Brain 用）----

_RETRY_TEMPLATE = load("retry_note")


@dataclass(frozen=True)
class RetryPromptReq:
    """`retry_prompt()` 的唯一输入——同一模式，只是这个调用没有现成的
    `communication` schema 可以复用（`ChooseOnceReq` 是决策请求的形状，
    跟"在已有 prompt 后追加一段纠正说明"不是同一件事），所以就地定义一个
    轻量 dataclass，不进 `schemas/communication`（那边放的是跨 Brain/Harness
    的协议，这个纯粹是 prompts 内部的拼接参数）。
    """

    base_prompt: str
    attempt: int
    reason: str
    raw: str


def retry_prompt(req: RetryPromptReq) -> str:
    """在 `req.base_prompt` 末尾拼一段纠正说明，用于失败重试的下一次尝试。

    **追加，不重新渲染 `build_prompt()`**：`base_prompt` 前缀一个字节不变，
    多次重试尝试才能共享同一段 prompt 缓存。前面两个换行是刻意的：
    `retry_note.md` 里的内容从 `---` 开始，留出和上文的视觉分隔——这两行
    属于"怎么拼接"，不属于 prompt 文字本身，所以写在这里而不是进 `.md` 文件。

    早一版重试是原样再问一遍，指望模型的随机性碰对——那等于把三次调用当一次用，
    而且最常见的那类错误（判据里写屏幕坐标）是**系统性的**，重试多少次都一样错。

    拼出追加在 prompt 末尾的那段纠正说明。
    """
    return (
        req.base_prompt
        + "\n\n"
        + _RETRY_TEMPLATE.render(attempt=req.attempt, reason=req.reason, raw=req.raw)
    )
