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
- **不判成败，也不数步。** 「任务达成了没有」要一次独立的模型调用，而 world
  不该认识 LLM；「走了几步」是循环的账，同一个世界要能跑不同步数上限的任务。
  两件事都在 `Harness` 里。world 只回答「世界现在什么样」和「我还在不在」。

## observe() 必须缓存

契约写明它幂等只读，但每调一次就是一次 VLM 调用。按帧哈希缓存：画面没变直接返回。
不缓存的话 `get_action_space()` 与 `perceive()` 各调一次，**每步感知成本翻倍**。
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
    BUTTON_FACING,
    INTERACT_KEY,
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

MAX_NOTES = 4
"""同一帧里最多留几条细看的答案。

`inspect` 不推进世界，所以 `step()` 的清空永远轮不到——没有上限的话
一帧里能一直问下去，而这段文字**同时进决策 prompt 和判定 prompt**。
"""

ALL_BUTTONS: tuple[str, ...] = ("a", "b", "up", "down", "left", "right", "start", "select")
"""世界支持的全部动作，**与状态无关**（`WorldPort.all_actions()` 的契约）。

就是 Game Boy 的八个键。掩码从中筛子集，动作空间本身不增长——
增长的是掩码之外的 skill library（机制二）。
"""

_FACING = BUTTON_FACING
"""方向键 → 朝向。定义在 `schemas/core.py`，**因为工具层也要用同一张表**
（它要算"这一步走的是哪个方向"）。

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
WITHIN_ACTION_FRAMES = 120  # 连按时，每次按完推进多少帧（1 秒）
AFTER_ACTION_FRAMES = 360  # 整个动作结束后再推进多少帧（2 秒），然后才感知
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
        inspect_prompt_name: str = "inspect_focus",
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
        self._inspect_prompt = load_prompt(inspect_prompt_name)
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
        self._facing = ""   # 未知。开局和过场之后都是未知，按一次方向键就确定
        self._notes: dict[str, str] = {}
        """`inspect()` 问出来的答案，**只在当前这一帧有效**。键是 focus。

        推进世界就清空：它们描述的是那一帧画面，留到下一帧就是过期事实，
        而过期事实比没有事实更糟——大脑分不出它是新的还是旧的。

        **只增不改**：note 单独占一个 facts 键，不去覆盖 `landmarks` 之类的既有字段。
        合并两份可能冲突的语义描述要定一套优先级规则，而那套规则本身就会错；
        并排放着让大脑自己读，反而是它擅长的事。

        **按 focus 去重，而且有条数上限**（见 `_note`）。用 dict 而不是 list：
        `inspect` 不推进世界，所以同一帧里可以连着问很多次，而 `step()` 的清空
        永远轮不到。实测连问 6 次同一个问题，`facts["inspected"]` 从 0 涨到 231 字符，
        **同一条答案被原样拼了 6 遍**——重复的事实会被模型当成强证据，
        比过期事实更糟，而且这段文字同时进决策 prompt 和判定 prompt。
        """
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
        """
        assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"

        if self._state_path:
            with open(self._state_path, "rb") as f:
                self._pyboy.load_state(f)
            self._pyboy.tick(1)      # 读档后要 tick 一次才会重绘
        else:
            self._tick(BOOT_FRAMES)

        self._task, self._closed, self._cache = task, False, None
        self._facing = ""
        self._notes = {}
        result = self.observe()

        assert not result.observation.done, "reset() must return a fresh observation"
        return result

    def observe(self) -> PerceptionResult:
        """取当前观测。只读、幂等——**同一帧不会重复调用视觉模型**。

        `result.calls` 就是这次 `_perceive()` 产生的调用记录，命中缓存时为空列表。
        """
        assert self._task is not None, "observe() before reset()"

        screen, terrain, calls = self._perceive()
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
        if self._facing:
            facts["facing"] = self._facing
        if screen.options:
            facts["options"] = " / ".join(screen.options)
        if screen.cursor is not None:
            facts["cursor"] = str(screen.cursor)
        # 放最后：它是大脑自己追问出来的，优先级低于每步都有的那些字段，
        # 而且**只对这一帧有效**（推进世界就清空）。
        if self._notes:
            facts["inspected"] = " | ".join(
                f"{focus} → {answer}" for focus, answer in self._notes.items()
            )

        obs = Observation(
            # **step / done / success 由 Harness 盖章，这里只给占位值。**
            # world 交出来的是"世界现在什么样"，不是"这一局跑到哪了"——
            # 后者是循环的账，三家各记一份就是上一版步号回退的成因。
            step=0,
            # **结构化的位置也交出去。** `facts["where"]` 是给模型读的文本，
            # 而交互记忆的键要拿 `(map_id, x, y)` 去算——反解字符串是迟早要出错的事。
            place=terrain.place(),
            summary=_summarize(screen),
            facts=facts,
            done=self._closed,
            success=False,
        )
        return PerceptionResult(observation=obs, calls=calls)

    def inspect(self, focus: str) -> PerceptionResult:
        """对**同一帧**再问一次视觉模型，问一个具体的问题。

        前置条件：focus 非空。没有问题就没有细看，只有重复付钱。
        后置条件：答案并进 `facts["inspected"]`，下一次 `observe()` 就能读到；
            世界**不推进**，`step()` 之后自动清空。

        ## 为什么不是"再调一次 observe"

        `observe()` 按帧哈希缓存，同一帧再调返回的字节完全一样——**没有新信息**。
        真正让它有价值的是这里换了一份 prompt：不再问"这一帧是什么"，
        而是问"`(7,7)` 那格到底是门还是窗"。同一张图、不同的问题，
        才会得到不同的答案。

        失败不抛异常，把失败本身写成一条 note。细看是**锦上添花**：
        问不出来就问不出来，为它中断一局不划算，而留一条"这次没看清"
        至少让大脑知道别再问同一个问题。
        """
        assert self._task is not None, "inspect() before reset()"
        assert focus.strip(), "inspect() got an empty focus"
        assert not self._closed, "inspect() after the window was closed"

        # **整段都在 try 里**，包括取帧、读内存、渲染 prompt。
        # 契约写的是"失败不抛异常"，那就不能只护住模型调用那一行——
        # `render()` 用的是 `Template.substitute`，模板少一个占位符就抛 KeyError，
        # 而 prompt 正是最常改的那类文件。
        t0 = time.perf_counter()
        sha, tokens = "", {"input_tokens": "0", "output_tokens": "0"}
        try:
            png = self._frame_png()
            sha = hashlib.sha256(png).hexdigest()[:12]
            terrain = read_terrain(self._pyboy.memory)
            prompt = self._inspect_prompt.render(
                focus=focus, known_map=terrain.render(), legend=terrain_legend()
            )
            r = self._vision.describe(png, prompt)
            answer = r.text.strip() or "（模型没说什么）"
            tokens = {"input_tokens": str(r.input_tokens),
                      "output_tokens": str(r.output_tokens)}
            kind = ""
        except Exception as exc:  # noqa: BLE001  细看失败不该让一局崩掉
            answer = f"（没看清：{type(exc).__name__}）"
            kind = type(exc).__name__

        # token 字段**失败时也要有**（填 0）。`PerceptionResult.calls` 的后置条件
        # 要求每条都含 input/output_tokens；下游按 payload 累加成本的代码
        # 碰到缺字段的记录只会 KeyError 或静默漏算。
        record = {
            **tokens,
            "frame_sha": sha,
            "prompt_sha": self._inspect_prompt.sha,
            "latency_ms": str(int((time.perf_counter() - t0) * 1000)),
            "attempt": "1",
            "ok": str(not kind),
            "raw": answer,
        }
        self._note(focus, answer)

        # **不清缓存**：`observe()` 每次都从缓存里的 ScreenState 重新组装 facts，
        # 而 `_notes` 是组装时才读的，所以新答案自然会出现在下一次观测里。
        #
        # calls **按发生顺序拼**：这次细看的那条记录在前，随后 `observe()`
        # 自己产生的记录（通常是空列表，因为帧没变、命中缓存）跟在后面——
        # 这就是因果顺序，不需要再靠"谁先记账"去调和。
        inner = self.observe()
        return PerceptionResult(
            observation=inner.observation, calls=[record, *inner.calls]
        )

    def _note(self, focus: str, answer: str) -> None:
        """记下一条细看的答案。**同一个问题只留最新一条，总数有上限。**

        问过的问题再问一次，答案覆盖而不是追加：重复的事实会被模型当成强证据。
        上限到了就丢掉最早的那条——`inspect` 不推进世界，
        所以这里是唯一挡得住"同一帧里一直问"的地方（`MAX_GOAL_DEPTH` 管的是拆解，
        管不到这个）。丢掉的是最早的，因为大脑最近关心的问题更可能还在用。
        """
        self._notes.pop(focus, None)            # 覆盖时也要换到队尾
        self._notes[focus] = answer
        while len(self._notes) > MAX_NOTES:
            self._notes.pop(next(iter(self._notes)))

    def all_actions(self) -> list[str]:
        """全部动作名，与状态无关。掩码是 harness 的事，不在这里做。"""
        return list(ALL_BUTTONS)

    def step(self, action: Action) -> ToolResult:
        """按一个键，推进固定帧数。

        前置条件：action.name 在 all_actions() 中。
        后置条件：`observation` 非空，是推进之后的新观测（`step` 未盖章）。

        **不报告"这一下有没有生效"。** 那个判断需要对比前后两次观察，
        而对比是上层的事——记忆层两头各存一份完整快照，正是为了回答它。
        world 只负责"我按了，世界推进了"。
        """
        assert self._task is not None, "step() before reset()"
        assert action.name in ALL_BUTTONS, f"unknown action {action.name!r}"
        assert not self._closed, "step() called after the window was closed"

        times = self._times(action)
        # **`a` 永远只按一次，连按一律夹到 1。**
        #
        # 我们一步只感知一次，所以连按会把中间那几帧**整个吃掉**。而 `a` 产出的
        # 恰恰是全项目最要紧的证据——对话框文字：
        #
        # - 判据最常用的就是它（"对话框里出现母亲说的话"）。连按三次推完整段对话，
        #   那几句话一帧都没被看到，最后一次还会把对话框关掉——判定器看到一个
        #   没有对话框的画面，**一局本该成功的 episode 被静默记成失败**。
        # - 档案里那一格的 `lines` 也只拿得到最后一句，中间几句直接丢。
        #   而"这是谁"往往就写在第一句里。
        #
        # 早一版只在**对话框已经开着**时夹。那漏掉了最常见的情形：
        # 对话框还没开，它对着 NPC 连按三次——第一次开、后两次推完，
        # 我们一句都没记下。`a` 的收益全在中间那几帧上，**连按对它从来没有意义**。
        #
        # 方向键不夹：沿直线走几格是它省步数的正当手段，中间帧也没有证据。
        if action.name == INTERACT_KEY or (times > 1 and self._dialog_is_open()):
            times = 1
        if action.name in _FACING:
            self._facing = _FACING[action.name]
        for _ in range(times):
            self._pyboy.button(action.name, delay=PRESS_FRAMES)
            self._tick(WITHIN_ACTION_FRAMES)
        self._tick(AFTER_ACTION_FRAMES)      # 等世界落定，再感知
        self._notes = {}                        # 细看的答案只对那一帧有效
        # **缓存不在这里清。** `_perceive()` 自己按帧哈希判，画面真变了它自然会
        # 重新调模型；而按了键**画面没变**（对着空地按 a、朝墙走）时，
        # 清掉缓存就是白花一次感知，还会引入噪声——
        # 实测连着四步 frame sha 一模一样，模型却给出了不同的 overview，
        # 其中一步把地图下方的黑边认成了对话框。同一帧只问一次，这类抖动直接消失。

        result = self.observe()    # 缓存刚清过，这里是本步唯一一次真感知
        obs = result.observation
        asked = self._times(action)
        note = f"（按了 {times} 次）" if times > 1 else ""
        if asked > times:
            # **夹了要说**，否则大脑会以为自己连按了 N 次，
            # 而实际只走了一次——它下一步的推理就建立在错的前提上。
            why = "a 只能一次一次按" if action.name == INTERACT_KEY else "对话框开着"
            note = f"（{why}，连按 {asked} 次被夹成 1 次）"
        return ToolResult(
            message=obs.summary + note, observation=obs, calls=result.calls
        )


    def _dialog_is_open(self) -> bool:
        """当前这一帧有没有对话框。读的是缓存里的 `ScreenState`，不额外调模型。

        缓存为空（刚 reset、或上一步刚推进过）时保守地当作没有——
        那时下一次 `observe()` 才会知道，而夹连按是为了不丢证据帧，
        少夹一次的代价远小于为它多调一次感知。
        """
        return self._cache is not None and self._cache[1].overlay is Overlay.DIALOG

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
                self._closed = True   # 窗口被关，世界没了——这是 world 唯一的终止权
                return

    def _frame_png(self) -> bytes:
        import io

        buf = io.BytesIO()
        self._pyboy.screen.image.save(buf, format="PNG")
        return buf.getvalue()

    def _perceive(self) -> tuple[ScreenState, TerrainMap, list[dict[str, str]]]:
        """调视觉模型读当前画面，按帧哈希缓存。

        调用记录**作为返回值的一部分直接交出去**，不再攒进实例状态——
        谁调了这个方法，calls 就跟着这次调用的返回值一路往上传
        （`observe()` → `reset()`/`inspect()`），不需要额外的 drain 步骤，
        也就不存在"谁来得早谁来得晚"的记账错位（见 `PerceptionResult` 的说明）。

        失败：连续重试仍解析不出时抛 `PerceptionFailure`。
            不返回一个「空白状态」兜底——那会让大脑基于假观测决策，
            而且这类失败在 replay 里必须能被统计到。
        """
        png = self._frame_png()
        sha = hashlib.sha256(png).hexdigest()[:12]
        self.last_frame_sha = sha
        # **缓存命中就直接回，什么账都不产生。** 没调模型就没有账。
        if self._cache and self._cache[0] == sha:
            return self._cache[1], self._cache[2], []

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
                return screen, terrain, calls
            last = r.text[:200]

        raise PerceptionFailure(self._retries, f"unparsable output: {last!r}")

    def stop(self) -> None:
        self._pyboy.stop()

    def save_state(self, path: str) -> None:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            self._pyboy.save_state(handle)
        assert target.is_file(), f"save_state() did not create {target}"
