"""`WorldPort` 的唯一实现：PyBoy 模拟器 + 视觉模型的粘合层。

一帧画面变成 `Observation` 要经过三条来源，各管一段，互不替代：

    RAM      坐标、地图编号、朝向、地形通行图、门与招牌的位置   确定，不会读错
    视觉模型  场景类别、对话框文字、屏幕上有什么               会读错，所以要重试和记账

**感知按帧哈希缓存。** 同一帧内重复 `observe()` 不再调模型——感知是每步都要付钱的
那一项，而 Harness 一步之内会从好几个地方读观测。同一帧的观测因此是**幂等的**。

**朝向也从内存读**（精灵表 +9）。它曾经是从"我按过哪个方向键"推出来的，
那样开局和过场之后是未知的，而且不进存档、checkpoint 恢复不回来
（`docs/spec/harness/SPEC.md` 1.4 记的就是这个洞）。现在没有这个洞了。

模型调用记录跟着 `PerceptionResult` / `ToolResult` 的返回值走，这里不攒缓冲区。
更多设计记录见 `docs/spec/world/SPEC.md`。
"""

from __future__ import annotations

import hashlib
import pathlib
import time

from pyboy import PyBoy

from pokemon_agent.errors import PerceptionFailure
from pokemon_agent.interfaces.vision import VisionProvider
from pokemon_agent.prompts import load as load_prompt
from pokemon_agent.schemas.action import Action, ToolResult
from pokemon_agent.schemas.observation import (
    OVERLAY_ACTIONS,
    Observation,
    Overlay,
    PerceptionResult,
    Scene,
    ScreenState,
    TerrainMap,
    terrain_legend,
)
from pokemon_agent.schemas.task import Task
from pokemon_agent.world.ram import read_terrain

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

PRESS_FRAMES = 10          # 按键按住多少帧
WITHIN_ACTION_FRAMES = 120  # 连按时，每次按完推进多少帧（1 秒）
AFTER_ACTION_FRAMES = 360  # 整个动作结束后再推进多少帧（2 秒），然后才感知
BOOT_FRAMES = 600          # 无存档时空转多少帧越过开机 logo



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
    except Exception:  # noqa: BLE001  解析失败是预期内情况，由调用方重试
        return None


def _status_line(s: ScreenState) -> str:
    """给大脑读的自然语言状态。

    有意做得简短：详细字段在 `facts` 里，这句话只是让 prompt 有个上下文开头。

    把这一帧压成给大脑读的一句话。
    """
    where = {
        Scene.FIELD: "你在野外", Scene.INDOOR: "你在室内", Scene.BATTLE: "你在战斗中",
        Scene.MENU: "你在菜单里", Scene.SHOP: "你在商店", Scene.TRANSITION: "画面正在切换",
    }[s.scene]
    bits = [where + "。"]
    if s.overlay is Overlay.DIALOG and s.dialog_text:
        bits.append(f"对话框：「{s.dialog_text}」")
    elif s.overlay is Overlay.CHOICE and s.options:
        cur = f"，光标在第 {s.cursor + 1} 项" if s.cursor is not None else ""
        bits.append(f"可选项：{ '/ '.join(s.options) }{cur}")
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
        max_perceive_retries: int = 2,
        watch: bool = False,
        speed: int = 1,
    ) -> None:
        """
        前置条件：max_perceive_retries >= 1。

        存档在 **`reset()`** 里载入，不是构造时——这样每个 episode 都从逐字节相同的
        起点开始跑，A/B 对比的前提才成立。构造时只检查文件在不在。

        `state_path` **显式传入**，不用 PyBoy 默认的 `<rom>.state`：
        后面会有多个命名起点（真新镇出口 / 一号道馆前 / …），默认路径只有一个坑位，
        而且改 ROM 文件名就对不上。用哪个存档起跑要进 manifest。

        接好模拟器与视觉模型，备好缓存和推导状态。
        """
        assert max_perceive_retries >= 1, "max_perceive_retries must be >= 1"

        # 存档缺失在构造时就炸，不留到 reset()。
        # 留到 reset() 的话，PyBoy 已启动、provider 已装配、可能已经开始计费，
        # 报错位置离真正的原因隔了好几层，而这是个纯粹的配置问题。
        if state_path and not pathlib.Path(state_path).is_file():
            raise FileNotFoundError(
                f"找不到存档 {state_path}。用 `python -m probe.play` 走到起点后 `save` 一个，"
                "或者传 state_path=None 从开机跑起。"
            )
        if not pathlib.Path(rom).is_file():
            raise FileNotFoundError(f"找不到 ROM {rom}")

        # 同步：这个对象和 PyBoy 全程在同一个线程。
        # **不要把 PyBoy 挪到别的线程**——`tick()` 内部要泵 SDL 事件循环，
        # 而 SDL 要求窗口的创建与事件泵在同一线程，跨线程在 Windows 上直接挂死。
        self._pyboy = PyBoy(rom, window="SDL2" if watch else "null", scale=4)
        self._pyboy.set_emulation_speed(speed if watch else 0)
        self._vision = vision
        self._prompt = load_prompt(prompt_name)
        self._state_path = state_path
        self._retries = max_perceive_retries

        self._task: Task | None = None
        self._closed = False
        """窗口被关了。**这是 world 唯一有资格宣告的终止**——世界没了，跑不下去。

        「步数用尽」「任务达成」都不在这里判：前者是循环的事（只有 Harness 知道
        走了几步），后者要一次独立的模型调用（world 不认识 LLM）。
        world 只回答"我还在不在"。
        """
        self._cache: tuple[str, ScreenState, TerrainMap] | None = None
        self.last_frame_sha = ""

    # ---- WorldPort ----

    def reset(self, task: Task) -> PerceptionResult:
        """按任务重置。

        前置条件：task.max_steps > 0。
        后置条件：done 为 False。

        **`step` 不由 world 填**（恒为 0，由 Harness 盖章）。同一个世界要能跑
        不同步数上限的任务，"走了几步"就只能是循环的账。

        **`task` 进来只用于断言和将来按任务选起始存档**——world 不需要知道
        任务目标是什么。"现在要完成的是哪条"由 Harness 的目标栈保管：
        任务目标只是栈底那一条，而 agent 当下在做的是栈顶那条，两者常常不同。

        载入起点存档，清掉推导状态，返回第一帧观测。
        """
        assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"

        if self._state_path:
            with open(self._state_path, "rb") as f:
                self._pyboy.load_state(f)
            self._pyboy.tick(1)      # 读档后要 tick 一次才会重绘
        else:
            self._tick(BOOT_FRAMES)

        self._task, self._closed, self._cache = task, False, None
        result = self.observe()

        assert not result.observation.done, "reset() must return a fresh observation"
        return result

    def observe(self) -> PerceptionResult:
        """取当前观测。只读、幂等——**同一帧不会重复调用视觉模型**。

        `result.calls` 就是这次 `_perceive()` 产生的调用记录，命中缓存时为空列表。

        读当前这一帧，命中缓存就不再调模型。
        """
        assert self._task is not None, "observe() before reset()"

        frame_sha, screen, terrain, calls = self._perceive()
        overlay, text = screen.overlay, screen.dialog_text.strip()

        # **说有对话框却一个字都没抄出来 = 它把别的东西看成对话框了。**
        # 实测：室内地图下方的黑色边界被认成对话框，而同一帧（frame sha 一模一样）
        # 上一步它还判的是 none。降级成 none，并把这次误判记下来。
        #
        # 这条交叉检验不需要任何新的输入——**它只是拿模型自己的两个输出对账**。
        # 而 overlay 决定动作掩码，错一次大脑就会拿到一组它按不出效果的动作。
        misread = ""
        if overlay is Overlay.DIALOG and not text:
            overlay, misread = Overlay.NONE, "dialog_without_text"

        facts: dict[str, str] = {
            "scene": screen.scene.value,
            "overlay": overlay.value,
            **screen.fields,
        }
        # **对话框的文字必须进 facts，而且排在最前面。**
        # 漏了这一项的代价大得离谱：判定器看不到对话内容，
        # 「对话框里出现母亲说的话」这类判据**永远不可能成立**；
        # 而决策模型看不到，就会按先验编一句出来当成自己读到的。
        # 实测判定器自己说过：「对话框内容未提供，无法确认是否为母亲说的话」。
        if text:
            facts["dialog_text"] = text
        if misread:
            facts["perception_warning"] = misread
        # facts 是有序 dict，大脑按这个顺序读到，所以顺序本身就是一种表达：
        # 先整体（overview），再地图（walk_map），最后细节（landmarks）。
        if screen.overview:
            facts["overview"] = screen.overview
        # walk_map 来自模拟器内存，不是模型读出来的——它是这些事实里唯一 100% 的一项。
        facts["walk_map"] = terrain.render()
        # **全项目只有一套坐标。** `walk_map` 的行列号、`where`、`landmarks`、
        # `known_objects` 里的 `x= y=` 是同一套数，不需要任何换算
        # （见 `TerrainMap.render` 里为什么删掉了屏幕格）。
        # 写法统一成 `x=8 y=5` 而不是 `(8,5)`：括号对是旧屏幕格的写法，
        # 留着它只会让"这指的是哪一套"重新变成一个问题。
        facts["map_id"] = str(terrain.map_id)
        # 只留数据，不带解释。怎么读图写在动作说明里（`MAP_HINT`）——
        # **说明写一次就够，数据每步都要发**。
        facts["where"] = terrain.place().render()
        # **地标只有类型和位置，没有名字，而且用全局坐标。**
        # 名字（这是谁家、招牌上写什么）在总览画面里没有可观测的证据——
        # 招牌的字根本没渲染，所有的门都是同一个深色矩形。让视觉模型填，
        # 它就按先验编：真新镇既没有宝可梦中心也没有商店，它照样给出了
        # 「写着「POKéMON CENTER」的招牌」。名字要靠**走进去看见**再记住，
        # 那是记忆层的事（见 `TerrainMap.landmarks` 的完整说明）。
        if landmarks := terrain.render_landmarks():
            facts["landmarks"] = landmarks
        # 四邻单独给一行：它是唯一**相对"我"**的地形描述，所以是唯一能进记忆的那份
        # （`walk_map` 的原点跟着人走，跨步骤引用会自相矛盾——见 `Snapshot`）。
        facts["neighbors"] = terrain.render_neighbors()
        if terrain.facing:
            facts["facing"] = terrain.facing
        if screen.options:
            facts["options"] = " / ".join(screen.options)
        if screen.cursor is not None:
            facts["cursor"] = str(screen.cursor)

        obs = Observation(
            # **step / done / success 由 Harness 盖章，这里只给占位值。**
            # world 交出来的是"世界现在什么样"，不是"这一局跑到哪了"——
            # 后者是循环的账，三家各记一份就是上一版步号回退的成因。
            step=0,
            # **结构化的位置也交出去。** `facts["where"]` 是给模型读的文本，
            # 而交互记忆的键要拿 `(map_id, x, y)` 去算——反解字符串是迟早要出错的事。
            place=terrain.place(),
            status=_status_line(screen),
            facts=facts,
            done=self._closed,
            success=False,
        )
        return PerceptionResult(observation=obs, frame_sha=frame_sha, calls=calls)

    def all_actions(self) -> list[str]:
        """全部动作名，与状态无关。掩码是 harness 的事，不在这里做。

        列出这个世界支持的全部动作名。
        """
        return list(ALL_BUTTONS)

    def step(self, action: Action) -> ToolResult:
        """按完整条动作链，推进固定帧数，**只在结尾感知一次**。

        前置条件：每一段的按键都在 all_actions() 中。
        后置条件：`observation` 非空，是整条链跑完之后的新观测（`step` 未盖章）。

        **一次决策 = 一次感知。** 段与段之间不感知：每次感知是一次视觉模型调用，
        `up×4 -> down×2` 要是每按一次感知一次，一步就是六次调用、十几秒，
        而中间那五帧没有任何会被用到的信息——多段链按规则只能是移动键。

        **不报告"这一下有没有生效"。** 那个判断需要对比前后两次观察，
        而对比是上层的事——记忆层两头各存一份完整快照，正是为了回答它。
        world 只负责"我按了，世界推进了"。

        按完整条链、推进固定帧数，返回新观测。
        """
        assert self._task is not None, "step() before reset()"
        assert not self._closed, "step() called after the window was closed"
        segments = action.segments()
        for segment in segments:
            assert segment.name in ALL_BUTTONS, f"unknown action {segment.name!r}"

        # **收到什么就按什么，这里不改写。** 「`a` 只按一次」这类规则在
        # `Brain._parse` 里就已经定死了（见那里的说明）——执行层再悄悄夹一次，
        # 大脑交出去的链和真正发生的链就对不上，而它下一步的推理建立在前者上。
        for segment in segments:
            for _ in range(segment.times):
                self._pyboy.button(segment.name, delay=PRESS_FRAMES)
                self._tick(WITHIN_ACTION_FRAMES)

        self._tick(AFTER_ACTION_FRAMES)      # 等世界落定，再感知
        # **缓存不在这里清。** `_perceive()` 自己按帧哈希判，画面真变了它自然会
        # 重新调模型；而按了键**画面没变**（对着空地按 a、朝墙走）时，
        # 清掉缓存就是白花一次感知，还会引入噪声——
        # 实测连着四步 frame sha 一模一样，模型却给出了不同的 overview，
        # 其中一步把地图下方的黑边认成了对话框。同一帧只问一次，这类抖动直接消失。

        result = self.observe()    # 整条链唯一的一次真感知
        obs = result.observation
        return ToolResult(observation=obs, calls=result.calls)

    # ---- 内部 ----

    def _tick(self, frames: int) -> None:
        """推进 N 帧。**逐帧 tick**——`tick(n)` 只在最后限速一次，

        批量调用在 watch 模式下会让画面一跳一跳，逐帧才是平滑的实时。
        无头模式不限速，逐帧的额外开销可以忽略。

        逐帧推进 N 帧。
        """
        for _ in range(frames):
            if not self._pyboy.tick(1):
                self._closed = True   # 窗口被关，世界没了——这是 world 唯一的终止权
                return

    def _frame_png(self) -> bytes:
        """把当前画面截成 PNG 字节。"""
        import io

        buf = io.BytesIO()
        self._pyboy.screen.image.save(buf, format="PNG")
        return buf.getvalue()

    def _perceive(self) -> tuple[str, ScreenState, TerrainMap, list[dict[str, str]]]:
        """调视觉模型读当前画面，按帧哈希缓存。

        调用记录**作为返回值的一部分直接交出去**，不再攒进实例状态——
        谁调了这个方法，calls 就跟着这次调用的返回值一路往上传
        （`observe()` → `reset()`/`perceive()`），不需要额外的 drain 步骤，
        也就不存在"谁来得早谁来得晚"的记账错位（见 `PerceptionResult` 的说明）。

        失败：连续重试仍解析不出时抛 `PerceptionFailure`。
            不返回一个「空白状态」兜底——那会让大脑基于假观测决策，
            而且这类失败在 replay 里必须能被统计到。

        调一次视觉模型读画面，按帧哈希缓存。
        """
        png = self._frame_png()
        sha = hashlib.sha256(png).hexdigest()[:12]
        # 属性仍然留着：`GameTools` 拿它做动作空间的过期检查（"这份动作空间是不是
        # 上一帧的"）。但**产出给调用方的那一份走返回值**，和 `calls` 同一个理由。
        self.last_frame_sha = sha
        # **缓存命中就直接回，什么账都不产生。** 没调模型就没有账。
        if self._cache and self._cache[0] == sha:
            return sha, self._cache[1], self._cache[2], []

        # **地形先读，而且和图片一起发给模型。**
        # 它是确定的（抄的是游戏自己的碰撞判定），所以它是骨架；
        # 模型不再回答"这格能不能走"，而是在一张已经正确的骨架上标语义——
        # 哪一格是门、是招牌、是人。它擅长的正是这个。
        terrain = read_terrain(self._pyboy.memory)
        prompt = self._prompt.render(known_map=terrain.render())

        calls: list[dict[str, str]] = []
        last = ""
        for attempt in range(1, self._retries + 1):
            t0 = time.perf_counter()
            r = self._vision.describe(png, prompt)
            screen = parse_screen(r.text)
            calls.append({
                "frame_sha": sha,
                "prompt_sha": self._prompt.sha,
                "input_tokens": str(r.input_tokens),
                "output_tokens": str(r.output_tokens),
                "latency_ms": str(int((time.perf_counter() - t0) * 1000)),
                "attempt": str(attempt),
                "ok": str(screen is not None),
                "raw": r.text,
            })
            if screen is not None:
                self._cache = (sha, screen, terrain)
                return sha, screen, terrain, calls
            last = r.text[:200]

        raise PerceptionFailure(self._retries, f"unparsable output: {last!r}")

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
