"""`WorldPort` 的唯一实现：PyBoy 模拟器 + 视觉模型的粘合层。

一帧画面变成 `Observation` 要经过三条来源，各管一段，互不替代：

    RAM      坐标、地图编号、朝向、地形通行图、门与招牌的位置   确定，不会读错
    屏幕解码  屏幕字符缓冲：对话 / 选项 / 光标（尽力切）+ 整屏原样   字符确定，切分尽力
    视觉模型  场景类别、概况、对话框文字、屏幕上有什么           会读错，所以要重试和记账

task 层（`perceive_task()`）只用前两条；episode 层三条都用，文字字段以视觉为准，
整屏原样（`Facts.screen`）两层都给，让模型自己对照。叠加层 DIALOG 只给严格的对话帧
（`ScreenText.strict_dialog`），其余给 CHOICE / NONE（掩码相同、都放开）。

**感知按帧哈希缓存。** 同一帧内重复 `observe()` 不调模型——感知是每步都要付钱的
那一项，而 Harness 一步之内会从好几个地方读观测。同一帧的观测因此是**幂等的**。

**朝向从内存读**（精灵表 +9），不按按键推断——按键推断在开局和过场之后是
未知的，且不进存档、checkpoint 恢复不回来。

模型调用记录跟着 `Perceived` 的返回值走，这里不攒缓冲区。
更多设计记录见 `docs/spec/world/SPEC.md`。
"""

from __future__ import annotations

import io
import pathlib
from dataclasses import dataclass

from pyboy import PyBoy

from pokemon_agent.world import VisionProvider

from .action_space import compute_action_space
from .interface import (
    OVERLAY_ACTIONS,
    ActionSpace,
    Facts,
    Perceived,
    ScreenText,
    TaskObservation,
    TaskPerceived,
    TerrainMap,
)
from .perceive_frame import (
    _battle_fields,
    _png_data_uri,
    perceive_frame,
)
from .prompts import load as load_prompt
from .ram import read_terrain
from .readout import read_readout
from .scene import classify_scene
from .screen_text import layout_field, overlay_of, read_screen_text
from .scripts.takeover import takeover_view


@dataclass
class _Task:
    """`reset()`/`set_task()` 收到的裸字段，攒成一个内部记账用的小结构。

    **不是模块间的信封**——只在这个文件里用，字段就是 `Task`
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
WITHIN_ACTION_FRAMES = 1 * GB_FPS  # 连按时，每次按完推进多少帧（1 秒）
AFTER_ACTION_FRAMES = 10 * GB_FPS  # 整条链按完后再推进多少帧（10 秒），然后才感知
BOOT_FRAMES = 10 * GB_FPS  # 无存档时空转多少帧越过开机 logo


def _ram_status(terrain: TerrainMap, text: ScreenText) -> str:
    """纯 RAM 观测的状态行：位置、朝向，加上屏幕文字能确定的对话 / 选项 / 光标。

    **不写"你在野外"这类场景词**（只有战斗能从内存确定）：编一句出来就是在假观测上做决策。
    """
    facing = f"，朝向 {terrain.facing}" if terrain.facing else ""
    bits = [f"（这一帧只读了内存）{terrain.place().render()}{facing}"]
    if text.in_battle:
        bits.append("战斗中")
    if text.dialog_text:
        bits.append(f"对话框：「{text.dialog_text}」")
    if text.options:
        bits.append(f"可选项：{'/ '.join(text.options)}，光标在 {text.cursor}")
    return "。".join(bits)


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
        speed: int = 0,
    ) -> None:
        """
        感知重试预算不在这里——`perceive_once()` 只问一次，重试循环与预算
        （`PERCEPTION_MAX_RETRIES`）在 **`GameTools.perceive_with_retry()`** 手里
        （0913 从 harness 节点搬回 tool 层，理由见 `world/errors.py` 的模块 docstring）。

        存档在 **`reset()`** 里载入，不是构造时——这样每个 episode 都从逐字节相同的
        起点开始跑，A/B 对比的前提才成立。构造时只检查文件在不在。

        `state_path` **显式传入**，不用 PyBoy 默认的 `<rom>.state`：
        后面会有多个命名起点（真新镇出口 / 一号道馆前 / …），默认路径只有一个坑位，
        而且改 ROM 文件名就对不上。用哪个存档起跑要进 manifest。

        **`watch` 与 `speed` 是两个独立的旋钮**（0914 解耦，此前是绑在一起的）：

        - `watch`：开不开 SDL2 窗口。开着能看见画面（跑挂了也看得见最后停在哪一帧），
          代价是多一条渲染路径；关着就是无头。
        - `speed`：模拟器速度。`0` = **不限速**（PyBoy 的约定，能跑多快跑多快，
          代价是一个核吃满）；`1` = 真实速度（过场看得清，CPU 占用大幅下降）。
          **它与窗口无关**——开窗照样可以不限速（"看得见 + 跑得最快"是合法组合），
          要看清过场时才动它；缺省 `0` 与解耦前的无头行为逐字相同。

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
        # **窗口与限速是两件事，各自一个参数**（0914 解耦）：
        # `watch` 只管开不开 SDL 窗口；`speed` 只管跑多快——`0` = 不限速（PyBoy 的
        # 约定，跑得最快），`1` = 真实速度（看得清过场）。四种组合都是一句话。
        #
        # 此前两者绑死成 `speed if watch else 0`：`speed` 只在 `watch=True` 时才有
        # 意义，于是"**开窗口但不限速**"这个组合根本表达不出来；而缺省 `speed=1`
        # 又让无头那次恒走 0——参数名义上存在、实际只有一半有效。解耦后缺省
        # `speed=0`，无头行为与解耦前逐字相同。
        self._pyboy.set_emulation_speed(speed)
        self._vision = vision
        self._prompt = load_prompt(prompt_name)
        self._state_path = state_path
        self._rom = pathlib.Path(rom).read_bytes()
        """ROM 原样：接管脚本与接管视图从里面读道具价格这类常量表。"""

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
        """按任务重置。**不感知**——第一帧由调用方另调 `perceive_once()` / `perceive_task()` 拿。

        前置条件：max_steps > 0。

        **`step` 不由 world 填**（恒为 0，由 Harness 盖章）。同一个世界要能跑
        不同步数上限的任务，"走了几步"就只能是循环的账。

        **参数只用于断言和将来按任务选起始存档**——world 不需要知道任务目标是
        什么，这几个裸字段是 `Task`（brain 的类型，world 不依赖它）
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

    def save_state(self) -> bytes:
        """模拟器完整状态 → 字节串（`pyboy.save_state`）。不推进世界。

        后置条件：返回非空字节串。
        """
        buf = io.BytesIO()
        self._pyboy.save_state(buf)
        data = buf.getvalue()
        assert data, "pyboy.save_state produced no bytes"
        return data

    def load_state(self, data: bytes) -> None:
        """字节串 → 模拟器完整状态（`pyboy.load_state`）。**读档后不 tick**。

        与 `reset` 读起点存档不同：那里要 tick 一次让画面进帧槽；这里 PyBoy 读档已恢复画面
        与内存（09-25 实测：读档后画面与 0xC000–0xDFFF 内存哈希与存档时相同，再存一次逐字节
        相同；多 tick 一帧则内存哈希变化），恢复点必须等于存档点。
        前置条件：`data` 非空。
        """
        assert data, "load_state() got empty bytes"
        self._pyboy.load_state(io.BytesIO(data))

    def get_action_space(self) -> ActionSpace:
        """按当前这一帧算能力掩码（纯函数委托，见 `world/action_space.py`）。

        帧从 `perceive_task()` 拿——它是 RAM 档感知，不调模型，读一帧的代价
        只有一个内存快照，不值得为此在 Port 上另开一个"当前帧"出口。
        """
        assert self._task is not None, "get_action_space() before reset()"
        observation = self.perceive_task().observation
        return compute_action_space(observation, list(ALL_BUTTONS))

    def all_actions(self) -> list[str]:
        """全部动作名，与状态无关。掩码是 harness 的事，不在这里做。

        列出这个世界支持的全部动作名。
        """
        return list(ALL_BUTTONS)

    def step(self, segments: list[tuple[str, int]], *, settle: bool = True) -> None:
        """按下去，推进固定帧数。**不感知**——之后那一帧由 Harness 调
        `perceive_once()`（episode 层）或 `perceive_task()`（task 层）拿。

        segments：`(按键名, 连按次数)` 的列表——`Action.sequence`
            拆开的裸字段。
            执行层恒传单键（一段、一次）：连按已经在 Harness 那边展开。
        settle：按完要不要给世界一段无输入演化时间（见步骤 3）。
        前置条件：每一段的按键都在 all_actions() 中。

        **谁决定感知频率，谁承担代价。** 这里只负责"按到位 + 可选地等世界自己
        走完"，一次调几个键由调用方决定；`up×4 -> down×2` 拆成 6 次调用时，
        中间那 5 次调用方只读内存、不烧视觉模型——那个取舍在 Harness 的循环
        结构里，不在这。

        步骤 1：校验每一段按键都合法。
        步骤 2：逐段按下、推进。
        步骤 3：`settle` 为真时给世界一段无输入演化时间，再交回控制权。
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

        # 步骤 3。**按完之后给世界 10 秒自己演化，再交回控制权——`settle=False`
        # 就不等。**
        #
        # 这一段里不按任何键，纯 tick。它等的是**按键按下去之后才开始、
        # 而且不需要再按键就会自己走完**的那些过程：换图的淡入淡出、
        # 战斗开场动画、对话框逐字打出、菜单弹出的那几帧、遭遇触发时的闪屏。
        # 等不够就感知，抄到的是一张过场中间的画面——视觉模型会照着那张半成品
        # 填 scene 和 fields，而**那一帧对应的状态在下一步已经不存在了**，
        # 决策和判定都建立在一个不再为真的世界上。
        #
        # **链中间的键不等。** 它们只读内存判"位置动没动、换没换图"，而那两件事
        # 只取决于按键自己推进了多少帧，不取决于过场走完没有；等它反而是白等。
        # 链尾（和单键动作）必须等——那一帧要交给 `judge` 看。
        #
        # `speed=1`（要看清画面时）按真实速度演化：过场动画值得被看到，而不是
        # 瞬间跳变；缺省 `speed=0` 不限速，这 10 秒游戏时间的 tick 本身是瞬间的。
        if settle:
            self._tick(AFTER_ACTION_FRAMES)

    def perceive_task(self) -> TaskPerceived:
        """task 层的一帧：**不问模型**，只读内存与屏幕缓冲（`_ram_observe`）。

        task 层每键都走这一档。
        """
        assert self._task is not None, "perceive_task() before reset()"
        png = self._frame_png()
        terrain = read_terrain(self._pyboy.memory)
        return self._ram_observe(terrain, read_screen_text(self._pyboy.memory), png)

    def perceive_once(self) -> Perceived:
        """感知当前这一帧（episode 层）：**只问一次视觉模型，不重试**。

        调用方（`GameTools.perceive_with_retry`，0913 起在 tool 层）在
        `reset()`/`step()` 之后调它拿观测；重试预算与循环归调用方管
        ——这里失败就抛，不自己再问一次。

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

        截图在这里，其余（地形、视觉、解析、拼装）全在 `perceive_frame.py::perceive_frame`。
        """
        assert self._task is not None, "perceive_once() before reset()"
        return perceive_frame(
            self._frame_png(),
            self._pyboy.memory,
            template=self._prompt,
            vision=self._vision,
            closed=self._closed,
        )

    def _ram_observe(self, terrain: TerrainMap, text: ScreenText, png: bytes) -> TaskPerceived:
        """只读内存的观测——**这一档不调视觉模型**。

        内存答得出的：坐标、朝向、地标、通行图、地图编号，以及从屏幕 tile 缓冲
        解码出的对话、选项、光标（`screen_text.read_screen_text`）和战斗标志。
        叠加层由这几样确定性推出：有光标 = CHOICE，否则有对话 = DIALOG，否则 NONE。
        `Facts.scene` 只在战斗时能确定（BATTLE），其余留空；概况留空。标 `perceived=False`。
        产出 task 层的 `TaskObservation`：另带场合（`scene.classify_scene`）；画面字段二选一——
        屏上有字只给 `screen`，没字（走路）只给 `walk_map`。

        截图照截：帧的可得性与"有没有人看过它"无关。

        解码切不出的界面（队伍列表、数量框、起名键盘……）字段为空或不全，不补视觉：
        整屏原样在 `screen` 里，由模型自己读。
        """
        overlay = overlay_of(text)
        mem = self._pyboy.memory
        scene = classify_scene(text, mem)
        facts = Facts(
            scene=Facts.Scene.BATTLE if text.in_battle else None,
            overlay=overlay,
            where=terrain.place().render(),
            facing=terrain.facing or "",
            neighbors=terrain.render_neighbors(),
            landmarks=terrain.landmarks(),
            dialog_text=text.dialog_text,
            options=text.options,
            cursor=text.cursor or None,
            walk_map="" if text.screen else terrain.render(),
            map_id=terrain.map_id,
            screen=text.screen,
            **_battle_fields(mem),
            **layout_field(text),
        )
        return TaskPerceived(
            observation=TaskObservation(
                step=0,
                place=terrain.place(),
                status=_ram_status(terrain, text),
                facts=facts,
                done=self._closed,
                perceived=False,
                scene=scene,
                takeover=takeover_view(scene, text, mem, self._rom),
            ),
            frame_png=_png_data_uri(png),
            ram=read_readout(mem, text, text_source="decode"),
        )

    # ---- 内部 ----

    def _tick(self, frames: int) -> None:
        """推进 N 帧。**逐帧 tick**——`tick(n)` 只在最后限速一次，

        批量调用在 `speed=1`（要看清画面时）会让画面一跳一跳，逐帧才是平滑的实时。
        不限速（`speed=0`，缺省）时逐帧的额外开销可以忽略。
        """
        for _ in range(frames):
            if not self._pyboy.tick(1):
                self._closed = True  # 窗口被关，世界没了——这是 world 唯一的终止权
                return

    def _frame_png(self) -> bytes:
        """把当前画面截成 PNG 字节。"""
        import io

        buf = io.BytesIO()
        self._pyboy.screen.image.save(buf, format="PNG")
        return buf.getvalue()

    def stop(self) -> None:
        """关掉模拟器。"""
        self._pyboy.stop()

    def evolve(self, frames: int) -> None:
        """无输入推进 N 帧——世界自己演化（音乐、动画、NPC 走动），不感知。

        决策等待期间的 evolve 已经从 harness 里去掉了（决策改成同步调用，
        重试循环在 `BrainTool.choose()`）——缺省 `speed=0`
        （不限速）时世界跑得比等待快，演化填充空闲省不出时间，异步等待反而是多余
        的复杂度。这个方法仍是 `WorldPort` 契约的一部分，只是暂时没有调用方；
        world 只负责按 `speed` 演化（与开不开窗口无关），不管调用方是谁。
        窗口被关时 `_tick` 会置 `_closed`，下次感知自然看到 done——这里不用管。
        """
        assert frames >= 0, f"evolve() got negative frames: {frames}"
        self._tick(frames)
