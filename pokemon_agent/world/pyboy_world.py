"""`WorldPort` 的真实实现 —— PyBoy + 视觉感知。

## 分层：感知在 world，掩码在 harness

`WorldPort.observe()` 的契约是交出 `Observation`（含 `summary` 与 `facts`），
而从像素产出这两样必须调 VLM——所以**感知只能在 world 里**，否则交不出合同要求的东西。

但**掩码是 harness 的策略**（CLAUDE.md 已定），而掩码规则依赖 `overlay`，那是感知的产物。
解法不改任何契约：**把 `scene` 与 `overlay` 放进 `Observation.facts`**。
`facts` 本就是 Observation 的公开部分，harness 读它做掩码不算越界。

    observe()  →  VLM → ScreenState → Observation(facts={"scene":…, "overlay":…, …})
    harness    →  读 facts["overlay"] → OVERLAY_ACTIONS 查表

感知是能力（world），掩码是策略（harness），边界与原设计一致。

## 时序：同步 + 固定缓冲

    按一次键 → 推进 1 秒 → （若连按，重复）→ 推进 2 秒 → 感知

**曾用「连续 N 帧不变」判稳定，不行**：草丛、水面、NPC 走动、闪烁光标、
战斗中的呼吸动画——很多画面根本不会静止，等稳定会大面积超时。

**也曾把模拟器放进后台线程异步跑**，让模型的思考时间充当天然的等待。
那样动画问题自己就没了，但代价是不可复现（同一存档跑两次结果不同），
而且线程、队列、条件变量、退出时唤醒等待者……一堆复杂度全是为了这一个好处。
**固定缓冲用远少的代码换到了同一个效果的九成，还顺带把可复现性拿了回来。**

剩下的风险是偶尔感知到动画中间帧——那是概率问题不是正确性问题，
可以量（感知失败率），不必先解决掉。

## 另外两个取舍

- **不判断动作有没有生效。** 画面本来就在动，像素比对量不出因果。
  动作没生效的话，下一步的观测会照实反映，由大脑自己纠正。
- **成败判定注入，默认永不成功。** 真实判据（运行时由 LLM 读历史与状态）属于上层，
  world 只负责「用满 max_steps 就终止」。不在这里编一套任务逻辑——
  编出来的东西无法验证，还会挡住真实现。

## observe() 必须缓存

契约写明它幂等只读，但每调一次就是一次 VLM 调用。按帧哈希缓存：画面没变直接返回。
不缓存的话 `get_action_space()` 与 `perceive()` 各调一次，**每步感知成本翻倍**。
"""

from __future__ import annotations

import hashlib
import pathlib
import time
from collections.abc import Callable

from pyboy import PyBoy

from pokemon_agent.errors import PerceptionFailure
from pokemon_agent.interfaces.vision import VisionProvider
from pokemon_agent.prompts import load as load_prompt
from pokemon_agent.schemas.core import (
    OVERLAY_ACTIONS,
    Action,
    Observation,
    Overlay,
    Scene,
    ScreenState,
    Task,
    ToolResult,
)

ALL_BUTTONS: tuple[str, ...] = ("a", "b", "up", "down", "left", "right", "start", "select")
"""世界支持的全部动作，**与状态无关**（`WorldPort.all_actions()` 的契约）。

就是 Game Boy 的八个键。掩码从中筛子集，动作空间本身不增长——
增长的是掩码之外的 skill library（机制二）。
"""

_FACING: dict[str, str] = {"up": "north", "down": "south", "left": "west", "right": "east"}
"""方向键 → 朝向。

**朝向是我们自己的动作推出来的，不是看出来的。** 宝可梦里按方向键，
撞墙时人也会转过去（只是不移动），所以"按过 up"就等于"面朝北"，没有例外。
这是确定的量；而实测让 VLM 读朝向是 8 步 8 次全错。

朝向要紧是因为 `a` 作用在**面朝的那一格**上：不知道朝向就不知道会调查到什么。
"""

MAX_TIMES = 8
"""一个动作最多连按几次。

上限存在的理由：模型会写 `"times": "100"`。连按期间 agent 看不见中间状态，
撞墙了也会把剩下几次按完——这是时序抽象的经典取舍，次数是宏动作（机制二）的原始形态。

收益是**省感知调用**：走 5 格从 5 次 VLM 调用变成 1 次。
感知是每步都花钱的那一项，这一下把成本和延迟都砍到五分之一。
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
WITHIN_ACTION_FRAMES = 60  # 连按时，每次按完推进多少帧（1 秒）
AFTER_ACTION_FRAMES = 120  # 整个动作结束后再推进多少帧（2 秒），然后才感知
BOOT_FRAMES = 600          # 无存档时空转多少帧越过开机 logo



def parse_screen(text: str) -> ScreenState | None:
    """把视觉模型的输出解析成 `ScreenState`。

    容忍 ```json 包裹——模型最常见的格式偏差，为它多跑一轮不划算。
    其余一律不兜底：解析不出来就是解析不出来，交给调用方重试。
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1].removeprefix("json").strip()
    try:
        return ScreenState.model_validate_json(t)
    except Exception:  # noqa: BLE001  解析失败是预期内情况，由调用方重试
        return None


def _summarize(s: ScreenState) -> str:
    """给大脑读的自然语言状态。

    有意做得简短：详细字段在 `facts` 里，这句话只是让 prompt 有个上下文开头。
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
        success: Callable[[ScreenState, int], bool] | None = None,
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
        self._success = success or (lambda _s, _step: False)

        self._task: Task | None = None
        self._step = 0
        self._done = False
        self._won = False
        self._cache: tuple[str, ScreenState] | None = None
        self._facing = ""   # 未知。开局和过场之后都是未知，按一次方向键就确定
        self.last_calls: list[dict[str, str]] = []
        """最近一次 `_perceive()` 里发生的**每一次**模型调用。

        是列表不是单条：解析失败会重试，而失败的那几次同样烧了 token，
        只留最后一次就把它们的成本和原始输出丢了。

        world 契约里没有 TracePort，所以这里只**暴露**记录，由上层写进 trace。
        不在 world 里塞 trace 依赖——那会让它认识本不该认识的东西。
        """
        self.last_frame_sha = ""

    # ---- WorldPort ----

    def reset(self, task: Task) -> Observation:
        """按任务重置。

        前置条件：task.max_steps > 0。
        后置条件：step == 0、done 为 False、goal == task.goal。
        """
        assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"

        if self._state_path:
            with open(self._state_path, "rb") as f:
                self._pyboy.load_state(f)
            self._pyboy.tick(1)      # 读档后要 tick 一次才会重绘
        else:
            self._tick(BOOT_FRAMES)

        self._task, self._step, self._done, self._won, self._cache = task, 0, False, False, None
        self._facing = ""
        obs = self.observe()

        assert obs.step == 0 and not obs.done, "reset() must return a fresh observation"
        return obs

    def observe(self) -> Observation:
        """取当前观测。只读、幂等——**同一帧不会重复调用视觉模型**。"""
        assert self._task is not None, "observe() before reset()"

        screen = self._perceive()
        facts: dict[str, str] = {
            "scene": screen.scene.value,
            "overlay": screen.overlay.value,
            **screen.fields,
        }
        # **overview 排在 walk_map 前面。** facts 是有序 dict，大脑按这个顺序读到，
        # 顺序就是"先整体后细节"——和感知那边的输出顺序一致。
        if screen.overview:
            facts["overview"] = screen.overview
        if screen.walk_map:
            facts["walk_map"] = screen.render_walk_map()
        if screen.landmarks:
            facts["landmarks"] = "; ".join(screen.landmarks)
        if self._facing:
            facts["facing"] = self._facing
        if screen.options:
            facts["options"] = " / ".join(screen.options)
        if screen.cursor is not None:
            facts["cursor"] = str(screen.cursor)

        return Observation(
            step=self._step,
            goal=self._task.goal,
            summary=_summarize(screen),
            facts=facts,
            done=self._done,
            success=self._won,
        )

    def all_actions(self) -> list[str]:
        """全部动作名，与状态无关。掩码是 harness 的事，不在这里做。"""
        return list(ALL_BUTTONS)

    def step(self, action: Action) -> ToolResult:
        """按一个键，推进固定帧数。

        前置条件：action.name 在 all_actions() 中；当前 episode 未结束。
        后置条件：返回的 observation.step 等于调用前 + 1。

        **`ok` 恒为 True。** 「这一下有没有真的改变世界」在这个环境里没有便宜可靠的判据：
        画面本身就有动画，像素比对量不出因果。动作若无效，下一步的观测会照实反映，
        由大脑自己纠正——这比给一个不可靠的信号强。
        """
        assert self._task is not None, "step() before reset()"
        assert action.name in ALL_BUTTONS, f"unknown action {action.name!r}"
        assert not self._done, "step() called on a finished episode"

        times = self._times(action)
        if action.name in _FACING:
            self._facing = _FACING[action.name]
        before = self._step
        for _ in range(times):
            self._pyboy.button(action.name, delay=PRESS_FRAMES)
            self._tick(WITHIN_ACTION_FRAMES)
        self._tick(AFTER_ACTION_FRAMES)      # 等世界落定，再感知
        self._step += 1
        self._cache = None                      # 世界推进了，缓存失效

        screen = self._perceive()
        self._won = self._success(screen, self._step)
        self._done = self._won or self._step >= self._task.max_steps

        obs = self.observe()
        note = f"（按了 {times} 次）" if times > 1 else ""
        assert obs.step == before + 1, "step() must advance exactly one step"
        return ToolResult(ok=True, message=obs.summary + note, observation=obs)


    @staticmethod
    def _times(action: Action) -> int:
        """从 `args["times"]` 取连按次数，越界与非法值一律夹到合法区间。

        **不因为次数写错就判整个动作失败**：动作名是对的，只是参数不合规范，
        为它跑一轮重试不划算——判据同 ```json 包裹。

        后置条件：返回值落在 [1, MAX_TIMES]。
        """
        raw = action.args.get("times", "1")
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return 1
        return max(1, min(n, MAX_TIMES))

    # ---- 内部 ----

    def _tick(self, frames: int) -> None:
        """推进 N 帧。**逐帧 tick**——`tick(n)` 只在最后限速一次，

        批量调用在 watch 模式下会让画面一跳一跳，逐帧才是平滑的实时。
        无头模式不限速，逐帧的额外开销可以忽略。
        """
        for _ in range(frames):
            if not self._pyboy.tick(1):
                self._done = True    # 窗口被关，当作 episode 终止
                return

    def _frame_png(self) -> bytes:
        import io

        buf = io.BytesIO()
        self._pyboy.screen.image.save(buf, format="PNG")
        return buf.getvalue()

    def _perceive(self) -> ScreenState:
        """调视觉模型读当前画面，按帧哈希缓存。

        失败：连续重试仍解析不出时抛 `PerceptionFailure`。
            不返回一个「空白状态」兜底——那会让大脑基于假观测决策，
            而且这类失败在 replay 里必须能被统计到。
        """
        png = self._frame_png()
        sha = hashlib.sha256(png).hexdigest()[:12]
        if self._cache and self._cache[0] == sha:
            return self._cache[1]

        self.last_calls = []
        self.last_frame_sha = sha
        last = ""
        for attempt in range(1, self._retries + 1):
            t0 = time.perf_counter()
            r = self._vision.describe(png, self._prompt.text)
            screen = parse_screen(r.text)
            self.last_calls.append({
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
                self._cache = (sha, screen)
                return screen
            last = r.text[:200]

        raise PerceptionFailure(self._retries, f"unparsable output: {last!r}")

    def stop(self) -> None:
        self._pyboy.stop()
