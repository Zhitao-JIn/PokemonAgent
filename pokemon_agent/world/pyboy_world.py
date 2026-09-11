"""`WorldPort` 的唯一实现：PyBoy 模拟器 + 视觉模型的粘合层。

一帧画面变成 `Observation` 要经过三条来源，各管一段，互不替代：

    RAM      坐标、地图编号、朝向、地形通行图、门与招牌的位置   确定，不会读错
    视觉模型  场景类别、对话框文字、屏幕上有什么               会读错，所以要重试和记账

**感知按帧哈希缓存。** 同一帧内重复 `observe()` 不调模型——感知是每步都要付钱的
那一项，而 Harness 一步之内会从好几个地方读观测。同一帧的观测因此是**幂等的**。

**朝向从内存读**（精灵表 +9），不按按键推断——按键推断在开局和过场之后是
未知的，且不进存档、checkpoint 恢复不回来。

模型调用记录跟着 `Perceived` 的返回值走，这里不攒缓冲区。
更多设计记录见 `docs/spec/world/SPEC.md`。
"""

from __future__ import annotations

import base64
import pathlib

from pyboy import PyBoy

from dataclasses import dataclass

from pokemon_agent.errors import PerceptionAttemptFailed
from pokemon_agent.prompts import load as load_prompt
from pokemon_agent.providers import VisionProvider
from pokemon_agent.schemas.providers import VisionDescribeReq

from .frame_slot import FrameSlot
from .interface import OVERLAY_ACTIONS, Facts, Observation, Perceived, ScreenState
from .interface.domain import terrain_legend
from .ram import read_terrain


@dataclass
class _Task:
    """`reset()`/`set_task()` 收到的裸字段，攒成一个内部记账用的小结构。

    **不是模块间的信封**——只在这个文件里用，字段就是 `TaskForBrain`
    （brain 的类型，world 不依赖它）里 world 真正用得到的那几个。
    """

    task_id: str
    goal: str
    success_criteria: str
    max_steps: int
    initial_state_hint: str = ""

ALL_BUTTONS: tuple[str, ...] = ("a", "b", "up", "down", "left", "right", "start", "select")
"""世界支持的全部动作，**与状态无关**（`WorldPort.all_actions()` 的契约）。

就是 Game Boy 的八个键。掩码从中筛子集，动作空间本身不增长——
增长的是掩码之外的 skill library（机制二）。
"""

# 掩码表里出现的每个键都必须是世界认得的键。
#
# 这条**在导入时查**，不留给测试：两张表分处 schemas 和 world，
# 改了一边忘了另一边时，harness 会交出一个世界不认识的动作，
# 而错误要到大脑选中它、`step()` 才炸——离病因隔了三层。
assert {b for buttons in OVERLAY_ACTIONS.values() for b in buttons} <= set(ALL_BUTTONS), (
    "OVERLAY_ACTIONS references a button that the world cannot execute"
)

GB_FPS = 60  # Game Boy 大约每秒 60 帧；下面几个常量都按这个换算成秒
PRESS_FRAMES = 10  # 按键按住多少帧
WITHIN_ACTION_FRAMES = 2 * GB_FPS  # 连按时，每次按完推进多少帧（2 秒）
AFTER_ACTION_FRAMES = 10 * GB_FPS  # 整条链按完后再推进多少帧（10 秒），然后才感知
BOOT_FRAMES = 10 * GB_FPS  # 无存档时空转多少帧越过开机 logo


def parse_screen(text: str) -> ScreenState | None:
    """把视觉模型的输出解析成 `ScreenState`。

    容忍 ```json 包裹——模型最常见的格式偏差，为它多跑一轮不划算。
    其余一律不兜底：解析不出来就是解析不出来，交给调用方重试。

    把视觉模型吐的 JSON 解析成 `ScreenState`。
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1].removeprefix("json").strip()
    try:
        return ScreenState.model_validate_json(t)
    except ValueError:  # ValidationError / JSONDecodeError 都是它的子类
        # 解析失败是预期内情况（模型输出格式问题），由调用方重试；
        # 只捕 ValueError 家族，预期外异常（bug）照常上抛。
        return None


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


class PyBoyWorld:
    """真实的宝可梦红世界。"""

    def __init__(
        self,
        rom: str,
        vision: VisionProvider,
        *,
        state_path: str | None = None,
        prompt_name: str = "perceive_screen",
        watch: bool = False,
        speed: int = 1,
    ) -> None:
        """
        感知重试预算不在这里——`perceive_once()` 只问一次，重试循环与预算
        （`PERCEPTION_MAX_RETRIES`）在 `EpisodeHarness` 手里（见
        `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"）。

        存档在 **`reset()`** 里载入，不是构造时——这样每个 episode 都从逐字节相同的
        起点开始跑，A/B 对比的前提才成立。构造时只检查文件在不在。

        `state_path` **显式传入**，不用 PyBoy 默认的 `<rom>.state`：
        后面会有多个命名起点（真新镇出口 / 一号道馆前 / …），默认路径只有一个坑位，
        而且改 ROM 文件名就对不上。用哪个存档起跑要进 manifest。

        接好模拟器与视觉模型，备好缓存和推导状态。
        """
        # 存档缺失在构造时就炸，不留到 reset()。
        # 留到 reset() 的话，PyBoy 已启动、provider 已装配、可能已经开始计费，
        # 报错位置离真正的原因隔了好几层，而这是个纯粹的配置问题。
        if state_path and not pathlib.Path(state_path).is_file():
            raise FileNotFoundError(
                f"找不到存档 {state_path}。传 state_path=None 从开机跑起，"
                "或者用实验入口跑一局让它存下起点存档。"
            )
        if not pathlib.Path(rom).is_file():
            raise FileNotFoundError(f"找不到 ROM {rom}")

        # 同步：这个对象和 PyBoy 全程在同一个线程。
        # **不要把 PyBoy 挪到别的线程**——`tick()` 内部要泵 SDL 事件循环，
        # 而 SDL 要求窗口的创建与事件泵在同一线程，跨线程在 Windows 上直接挂死。
        #
        # `no_input=True`：**禁掉一切用户输入**。SDL2 窗口默认把按键映射成
        # PyBoy 事件（`P` = PAUSE_TOGGLE、`空格` = 限速切换、方向键 = 注入
        # 游戏输入）——agent 跑的时候任何人按一下键，要么把世界**暂停**
        # （paused=True 后 `tick()` 不推进帧但返回 True，run 空转、画面冻结），
        # 要么污染世界状态。这里是自动化测试场景，窗口只该"被看"不该"被玩"。
        # 副作用：窗口关闭事件（QUIT）也不再注入——watch 模式关窗不终止 run，
        # 可接受（无头模式本来就没有窗口事件）。
        self._pyboy = PyBoy(
            rom,
            window="SDL2" if watch else "null",
            scale=4,
            no_input=True,
        )
        # 无头模式（不 watch）不限速——没有人在看画面，演化按真实速度走
        # 只是在空烧时间。只有 watch=True 时才按 `speed` 限速，让过场动画
        # 看得清；无头批次跑得快，靠的就是这一行。
        self._pyboy.set_emulation_speed(speed if watch else 0)
        self._vision = vision
        self._prompt = load_prompt(prompt_name)
        self._state_path = state_path

        self._frames = FrameSlot()
        """实时画面的单槽管道：`_tick` 每帧生产，`latest_frame()` 消费（SSE）。"""

        self._task: _Task | None = None
        self._closed = False
        """窗口被关了。**这是 world 唯一有资格宣告的终止**——世界没了，跑不下去。

        「步数用尽」「任务达成」都不在这里判：前者是循环的事（只有 Harness 知道
        走了几步），后者要一次独立的模型调用（world 不认识 LLM）。
        world 只回答"我还在不在"。
        """

    # ---- WorldPort ----

    def reset(
        self,
        *,
        task_id: str,
        goal: str,
        success_criteria: str,
        max_steps: int,
        initial_state_hint: str = "",
    ) -> None:
        """按任务重置。**不感知**——第一帧由 Harness 调 `perceive_once()` 拿。

        前置条件：max_steps > 0。

        **`step` 不由 world 填**（恒为 0，由 Harness 盖章）。同一个世界要能跑
        不同步数上限的任务，"走了几步"就只能是循环的账。

        **参数只用于断言和将来按任务选起始存档**——world 不需要知道任务目标是
        什么，这几个裸字段是 `TaskForBrain`（brain 的类型，world 不依赖它）
        拆开后 world 真正用得到的那一份。"现在要完成的是哪条"由 Harness 的
        目标栈保管：任务目标只是栈底那一条，而 agent 当下在做的是栈顶那条，
        两者常常不同。

        步骤 1：载入起点存档（或空转过开机 logo）。
        步骤 2：清掉推导状态，标记这一局开始了。
        """
        assert max_steps > 0, f"max_steps must be > 0, got {max_steps}"

        # 步骤 1。
        if self._state_path:
            with open(self._state_path, "rb") as f:
                self._pyboy.load_state(f)
            # 读档后要 tick 一次才会重绘——走 _tick 而不是裸 pyboy.tick(1)：
            # 读档画面（起点存档里的那一帧）也要进帧槽，前端能立即看到
            # 起始画面，而不是等到第一次 evolve 才有帧。
            self._tick(1)
        else:
            self._tick(BOOT_FRAMES)

        # 步骤 2。
        self._task = _Task(task_id, goal, success_criteria, max_steps, initial_state_hint)
        self._closed = False

    def set_task(
        self,
        *,
        task_id: str,
        goal: str,
        success_criteria: str,
        max_steps: int,
        initial_state_hint: str = "",
    ) -> None:
        """只挂任务标记，**不动模拟器状态**——`reset()` 步骤 2 单独拎出来。

        用于 checkpoint 恢复：`load_state_bytes()` 已经把模拟器摆到了正确的
        那一帧，这里不需要（也不能）再走 `reset()` 的步骤 1（重新读档/空转），
        只需要把 `_task`/`_closed` 补上——它们是纯 Python 记账，不在存档字节里，
        `load_state_bytes()` 管不到（见 `episode_harness.resume()` 的调用点）。

        前置条件：max_steps > 0；调用前模拟器已经处于正确帧（`load_state_bytes()`
        或紧随其后的一次 `reset()`）。
        """
        assert max_steps > 0, f"max_steps must be > 0, got {max_steps}"
        self._task = _Task(task_id, goal, success_criteria, max_steps, initial_state_hint)
        self._closed = False

    def all_actions(self) -> list[str]:
        """全部动作名，与状态无关。掩码是 harness 的事，不在这里做。

        列出这个世界支持的全部动作名。
        """
        return list(ALL_BUTTONS)

    def step(self, segments: list[tuple[str, int]]) -> None:
        """按完整条动作链，推进固定帧数。**不感知**——链尾那一帧由 Harness
        调 `perceive_once()` 拿。

        segments：`(按键名, 连按次数)` 的列表——`ActionFromBrain.sequence`
            拆开的裸字段，world 不关心 `thought`/`rationale` 这些字段。
        前置条件：每一段的按键都在 all_actions() 中。

        **一次决策 = 一次感知。** 段与段之间不感知：每次感知是一次视觉模型调用，
        `up×4 -> down×2` 要是每按一次感知一次，一步就是六次调用、十几秒，
        而中间那五帧没有任何会被用到的信息——多段链按规则只能是移动键。

        步骤 1：校验每一段按键都合法。
        步骤 2：逐段按下、推进。
        步骤 3：整条链按完，给世界一段无输入演化时间，再交回控制权。
        """
        assert self._task is not None, "step() before reset()"
        assert not self._closed, "step() called after the window was closed"

        # 步骤 1。
        for name, _times in segments:
            assert name in ALL_BUTTONS, f"unknown action {name!r}"

        # 步骤 2。**收到什么就按什么，这里不改写。** 「`a` 只按一次」这类规则在
        # `Brain._parse` 里就已经定死了（见那里的说明）——执行层再悄悄夹一次，
        # 大脑交出去的链和真正发生的链就对不上，而它下一步的推理建立在前者上。
        for name, times in segments:
            for _ in range(times):
                self._pyboy.button(name, delay=PRESS_FRAMES)
                self._tick(WITHIN_ACTION_FRAMES)

        # 步骤 3。**按完之后给世界 10 秒自己演化，再交回控制权。**
        #
        # 这一段里不按任何键，纯 tick。它等的是**按键按下去之后才开始、
        # 而且不需要再按键就会自己走完**的那些过程：换图的淡入淡出、
        # 战斗开场动画、对话框逐字打出、菜单弹出的那几帧、遭遇触发时的闪屏。
        # 等不够就感知，抄到的是一张过场中间的画面——视觉模型会照着那张半成品
        # 填 scene 和 fields，而**那一帧对应的状态在下一步已经不存在了**，
        # 决策和判定都建立在一个不再为真的世界上。
        #
        # watch 模式下按真实速度演化：过场动画值得被看到，而不是
        # 瞬间跳变；无头模式不限速，这 10 秒游戏时间的 tick 本身是瞬间的。
        self._tick(AFTER_ACTION_FRAMES)

    def perceive_once(self) -> Perceived:
        """感知当前这一帧，**只问一次视觉模型，不重试**。

        调用方（`EpisodeHarness`）在 `reset()`/`step()` 之后调它拿观测；
        重试预算与循环归调用方管（见 `docs/ROADMAP.md` "重试循环该不该从
        brain 挪到 harness"）——这里失败就抛，不自己再问一次。

        `perceive_screen.md` 里硬写了"战斗指令框是 2×2"这条领域知识，是
        "领域知识该被检索、不该被硬编码进常驻 prompt"这条规则的**唯一例外**
        （对照 `decide_action/button_help.md`，那边的同一条知识已经改成
        泛指"横向多列排布"，交给 `$knowledge` 占位符去检索 `knowledge/
        battle_actions.md`）——这里不能这么做：这份 prompt 的职责就是
        **从像素判断 `scene` 本身**，此刻还不知道现在是不是战斗画面，
        自然也没法先按 `scene=battle` 去检索"战斗相关知识"再喂给它，
        检索的前提（已知场景）在这一步还不成立。

        失败：解析不出 `ScreenState` 时抛 `PerceptionAttemptFailed`（附这次
        的账）。**不返回一个「空白状态」兜底**——那会让大脑基于假观测决策，
        而且这类失败在 replay 里必须能被统计到。

        步骤 1：截当前画面、读地形（确定性，不是模型读出来的）。
        步骤 2：问一次视觉模型，解析不出来就把账封进异常抛出去。
        步骤 3：解析出来了，拼成完整观测交回去。
        """
        assert self._task is not None, "perceive_once() before reset()"

        # 步骤 1。
        png = self._frame_png()
        terrain = read_terrain(self._pyboy.memory)
        prompt = self._prompt.render(known_map=terrain.render(), terrain_legend=terrain_legend())

        # 步骤 2。
        # images 存 base64 字符串（与 `StepMemory.before_frame`/`after_frame`
        # 统一格式，见该字段文档）；这里是唯一产出原始字节的地方，编码就在这
        # 做——下游不用关心谁该编码。
        r = self._vision.describe(
            VisionDescribeReq(images=[base64.b64encode(png).decode()], prompt=prompt)
        )
        screen = parse_screen(r.text)
        call = {
            "input_tokens": str(r.input_tokens),
            "output_tokens": str(r.output_tokens),
            "cached_tokens": str(r.cached_tokens),
            "reasoning_tokens": str(r.reasoning_tokens),
            "ok": str(screen is not None),
            "raw": r.text,
            "prompt": prompt,
        }
        if screen is None:
            raise PerceptionAttemptFailed(call)

        # 步骤 3。
        overlay, text = screen.overlay, screen.dialog_text.strip()

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

        # **`Facts` 是结构化模型，字段该是什么类型就是什么类型。** 不再需要先把
        # `scene`/`overlay`/`landmarks` 渲染成文本塞进一个 `dict[str, str]`——
        # 判定层（`harness/object_interactions.py`）和记忆检索直接拿 `facts.scene`/
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
            # 视觉模型按当前 scene 自由给的字段（my_hp/foe_level/…）——`Facts` 的
            # `extra="allow"` 接住它们，不需要为每个 scene 各开一个具名字段。
            **screen.fields,
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
            done=self._closed,
        )
        return Perceived(
            observation=obs, calls=[call], frame_png=base64.b64encode(png).decode()
        )

    # ---- 内部 ----

    def _tick(self, frames: int) -> None:
        """推进 N 帧。**逐帧 tick**——`tick(n)` 只在最后限速一次，

        批量调用在 watch 模式下会让画面一跳一跳，逐帧才是平滑的实时。
        无头模式不限速，逐帧的额外开销可以忽略。

        每帧把画面副本塞进帧槽（`_frames`，O(1) 只换引用）——这是实时
        画面的生产端：任何推进（按键后演化、决策期演化、开局）都会让
        前端看到最新帧，不再依赖感知时点。

        逐帧推进 N 帧。
        """
        for _ in range(frames):
            if not self._pyboy.tick(1):
                self._closed = True  # 窗口被关，世界没了——这是 world 唯一的终止权
                return
            # `screen.image` 是 `frombuffer` 共享渲染缓冲的视图，下一帧 tick
            # 会覆盖底层数据——必须 copy() 出这一帧独有的像素副本再塞。
            image = self._pyboy.screen.image
            if image is not None:
                self._frames.push(image.copy())

    def latest_frame(self) -> bytes | None:
        """取最新一帧的 PNG 字节（消费者接口）；还没 tick 过返回 `None`。

        编码是惰性的——只在这被调用时才发生（SSE 端按自己的节奏取），
        生产者每帧只付出一次 `copy()` 的成本。
        """
        return self._frames.latest()

    def _frame_png(self) -> bytes:
        """把当前画面截成 PNG 字节。"""
        import io

        buf = io.BytesIO()
        self._pyboy.screen.image.save(buf, format="PNG")
        return buf.getvalue()

    def stop(self) -> None:
        """关掉模拟器。"""
        self._pyboy.stop()

    def save_state(self, path: str) -> None:
        """把模拟器状态存成一个文件。"""
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            self._pyboy.save_state(handle)
        assert target.is_file(), f"save_state() did not create {target}"

    def save_state_bytes(self) -> bytes:
        """把模拟器状态存成字节串（checkpoint 每步世界快照用，
        见 PLAN_checkpoint §2 三件套）。"""
        import io as _io

        buffer = _io.BytesIO()
        self._pyboy.save_state(buffer)
        return buffer.getvalue()

    def load_state_bytes(self, data: bytes) -> None:
        """从字节串恢复模拟器状态（checkpoint 恢复用）。"""
        import io as _io

        self._pyboy.load_state(_io.BytesIO(data))

    def evolve(self, frames: int) -> None:
        """无输入推进 N 帧——世界自己演化（音乐、动画、NPC 走动），不感知。

        决策等待期间的 evolve 已经从 harness 里去掉了（决策改成同步调用，
        见 `harness/utils.py` 的 `choose_with_retry`）——无头模式下世界不
        限速，演化填充空闲省不出时间，异步等待反而是多余的复杂度。这个方法
        仍是 `WorldPort` 契约的一部分，只是暂时没有调用方；world 只负责按
        `speed`（watch 时才限速，无头不限速）演化，不管调用方是谁。
        窗口被关时 `_tick` 会置 `_closed`，下次感知自然看到 done——这里不用管。
        """
        assert frames >= 0, f"evolve() got negative frames: {frames}"
        self._tick(frames)
