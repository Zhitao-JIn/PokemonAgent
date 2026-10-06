"""episode 档的一帧感知：截图 + 内存 → `Perceived`（只问一次视觉模型）。

`PyBoyWorld.perceive_once` 的全部逻辑在这里，它只负责截图并把模拟器内存交进来。
抽成纯函数是为了让**不起模拟器**的调用方（测评拿存下来的截图 + WRAM 快照）走同一个节点：
同一套地形读取、prompt 渲染、视觉调用、解析与 `Facts` 拼装，不另抄一份。
"""

from __future__ import annotations

from pokemon_agent.world import VisionProvider

from .battle_status import read_battle_status
from .interface import Facts, Memory, Observation, Perceived, ScreenState, ScreenText
from .interface.domain import terrain_legend
from .prompts import PromptTemplate
from .ram import read_terrain
from .readout import read_readout
from .screen_text import layout_field, overlay_of, read_screen_text
from .visual_perception import _png_data_uri, parse_screen, perceive_visual


def _checked_overlay(vision: Facts.Overlay, text: ScreenText) -> Facts.Overlay:
    """看档路径的叠加层：视觉说是对话框，还得屏幕解码认得是严格的对话帧，否则按解码推。"""
    if vision is Facts.Overlay.DIALOG and not text.strict_dialog:
        return overlay_of(text)
    return vision


def _status_line(s: ScreenState, cursor: str = "") -> str:
    """给大脑读的自然语言状态。

    有意做得简短：详细字段在 `facts` 里，这句话只是让 prompt 有个上下文开头。

    把这一帧压成给大脑读的一句话。
    """
    where = {
        Facts.Scene.FIELD: "你在野外",
        Facts.Scene.INDOOR: "你在室内",
        Facts.Scene.BATTLE: "你在战斗中",
        Facts.Scene.MENU: "你在菜单里",
        Facts.Scene.SHOP: "你在商店",
        Facts.Scene.TRANSITION: "画面正在切换",
        Facts.Scene.NAMING: "你在起名字",
        Facts.Scene.MAP_VIEW: "你在看地区总览地图",
    }[s.scene]
    bits = [where + "。"]
    if s.overlay is Facts.Overlay.DIALOG and s.dialog_text:
        bits.append(f"对话框：「{s.dialog_text}」")
    elif s.overlay is Facts.Overlay.CHOICE and s.options:
        # **读不出来要明写"读不出"。** 静默省略这半句的话，
        # 「可选项：A/ B/ C」和「可选项：A/ B/ C，光标在 A」扫过去几乎一样，
        # 而"没读出光标"和"光标在第一项"是完全不同的两件事。
        cur = f"，光标在 {cursor}" if cursor else "，光标读不出"
        bits.append(f"可选项：{'/ '.join(s.options)}{cur}")
    return "".join(bits)


def _battle_fields(mem: Memory) -> dict[str, str]:
    """战斗双方状态框压成 `Facts` 动态字段（`my_*` / `foe_*`）；不在战斗时为空。"""
    battle = read_battle_status(mem)
    return battle.facts_fields() if battle is not None else {}


def perceive_frame(
    png: bytes,
    memory: Memory,
    *,
    template: PromptTemplate,
    vision: VisionProvider,
    closed: bool = False,
) -> Perceived:
    """一帧截图 + 同一时刻的内存 → episode 档观测（只问一次视觉模型，不重试）。

    前置条件：`png` 与 `memory` 是同一帧（地形 / 屏幕解码读内存，场景 / 文字读截图）；
    `memory` 能按绝对地址读到 WRAM 与 bank 0 的 ROM（通行表在 bank 0）。
    失败：解析不出 `ScreenState`、或视觉调用本身失败时抛 `PerceptionAttemptFailed`（附这次的账）。
    `closed` 只是原样填进 `Observation.done`（世界层自己的信号）。

    步骤 1：读地形（确定性，不是模型读出来的）。
    步骤 2：问一次视觉模型，解析不出来就把账封进异常。
    步骤 3：拼成观测交回去。
    """
    # 步骤 1。
    terrain = read_terrain(memory)

    # 步骤 2：问一次视觉模型（屏幕解码也读一遍，给整屏原样与叠加层核对用）。
    ram_text = read_screen_text(memory)
    prompt = template.render(known_map=terrain.render(), terrain_legend=terrain_legend())
    # 帧在本层只编码一次（`_png_data_uri`，完整 data URI）——进模型、
    # 落盘（trace / step_memory）拿的都是**同一份字符串**，下游不存在
    # 第二种格式（0915 定，裸 base64 已废）。
    #
    # **把 `describe()` 的失败收编成本层的一次尝试失败**（0913 深夜十一）：
    # 实现（`brain/providers.py` 的 `_MultimodalMixin`）在"图片没真送到"时抛
    # `ImageNotDelivered`；本层的契约只认 `PerceptionAttemptFailed`
    # （见 `world/interface/world_port.py` 的失败段）。**world 不 import brain
    # 那个类**——它不关心上游抛的是什么名字，只知道"这一次没拿到描述"，
    # 于是就地包装成自己的词汇，把原因文本带过去。
    # 这样做的收益：`ImageNotDelivered` 可以安心归 brain（brain 才拷得走），
    # 而 world 这条链的失败出口始终只有 `PerceptionAttemptFailed` 一个
    # （`GameTools.perceive_with_retry` 只接它，耗尽后翻译成 tool 层的
    # `MaxRetriesExceeded`——world 的词汇跨不过 tool 层这座桥，见 `world/errors.py`）。
    visual = perceive_visual(png, prompt=prompt, vision=vision)
    screen, call = visual.screen, visual.call

    # 步骤 3：把"内存读出来的地形"和"模型读出来的屏幕"拼成一份观测。
    # 文字字段以视觉为准（0926 定）；整屏原样另放 `screen`，叠加层的 DIALOG 要解码也认。
    overlay, text = _checked_overlay(screen.overlay, ram_text), screen.dialog_text.strip()

    # **说有对话框却一个字都没抄出来 = 它把别的东西看成对话框了。**
    # 实测：室内地图下方的黑色边界被认成对话框，而**画面一动没动**的情况下
    # 上一步它还判的是 none。降级成 none，并把这次误判记下来。
    #
    # 这条交叉检验不需要任何新的输入——**它只是拿模型自己的两个输出对账**。
    # 而 overlay 决定动作掩码，错一次大脑就会拿到一组它按不出效果的动作。
    if overlay is Facts.Overlay.DIALOG and not text:
        overlay = Facts.Overlay.NONE

    # **地标只有类型和位置，没有名字，而且用全局坐标。**
    # 名字（这是谁家、招牌上写什么）在总览画面里没有可观测的证据——
    # 招牌的字根本没渲染，所有的门都是同一个深色矩形。让视觉模型填，
    # 它就按先验编：真新镇既没有宝可梦中心也没有商店，它照样给出了
    # 「写着「POKéMON CENTER」的招牌」。名字要靠**走进去看见**再记住，
    # 那是记忆层的事（见 `TerrainMap.landmarks` 的完整说明）。
    landmarks = terrain.landmarks()
    ram = read_readout(memory, ram_text, text_source="vlm")

    # **`Facts` 是结构化模型，字段该是什么类型就是什么类型。** 不再需要先把
    # `scene`/`overlay`/`landmarks` 渲染成文本塞进一个 `dict[str, str]`——
    # 判定层（`harness/episode/store/store_object_semantic_memory/rules.py`）
    # 和记忆检索直接拿 `facts.scene`/
    # `facts.landmarks` 这些结构化字段用，`render()`/`items()` 才做"转文本"，
    # 且只在真的要喂给大脑读、或者拼检索 query 的那一刻才发生。
    #
    # **全项目只有一套坐标。** `walk_map` 的行列号、`where`、`landmarks` 里的
    # `x= y=` 是同一套数，不需要任何换算（见 `TerrainMap.render` 里为
    # 什么删掉了屏幕格）。写法统一成 `x=8 y=5` 而不是 `(8,5)`：括号对是旧屏幕
    # 格的写法，留着它只会让"这指的是哪一套"重新变成一个问题。
    #
    # **对话框的文字必须进去。** 漏了这一项的代价大得离谱：判定器看不到对话
    # 内容，「对话框里出现母亲说的话」这类判据**永远不可能成立**；而决策模型
    # 看不到，就会按先验编一句出来当成自己读到的。
    facts = Facts(
        scene=screen.scene,
        overlay=overlay,
        where=terrain.place().render(),
        facing=terrain.facing or "",
        # 四邻是唯一**相对"我"**的地形描述，所以是唯一能进记忆的那份
        # （`walk_map` 的原点跟着人走，跨步骤引用会自相矛盾）。
        neighbors=terrain.render_neighbors(),
        landmarks=landmarks,
        dialog_text=text,
        options=screen.options,
        cursor=screen.cursor or "",
        overview=screen.overview,
        # walk_map 来自模拟器内存，不是模型读出来的——它是这些事实里唯一 100% 的一项。
        walk_map=terrain.render(),
        map_id=terrain.map_id,
        screen=ram_text.screen,
        **{**screen.fields, **_battle_fields(memory)},
        **layout_field(ram_text),
    )

    obs = Observation(
        # **step 由 Harness 盖章，这里只给占位值。**
        # world 交出来的是"世界现在什么样"，不是"这一局跑到哪了"——
        # 后者是循环的账。
        step=0,
        # **结构化的位置也交出去。** `facts.where` 是给模型读的文本，
        # 而交互记忆的键要拿 `(map_id, x, y)` 去算——反解字符串是迟早要出错的事。
        place=terrain.place(),
        status=_status_line(screen, facts.cursor or ""),
        facts=facts,
        # **`done` 是世界层自己唯一能报的信号**（窗口关没关）；
        # "这一局该不该结束"/"任务完不完成"归 `EpisodeRunState.done`/`.success`
        # ——世界压根不知道目标是什么，不给恒为 False 的占位值。
        done=closed,
        # 这一档问过视觉模型了，走的是"看"。
        perceived=True,
    )
    return Perceived(observation=obs, calls=[call], frame_png=_png_data_uri(png), ram=ram)


__all__ = ["parse_screen", "perceive_frame"]
