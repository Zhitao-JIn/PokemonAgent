"""harness —— 把「世界的能力」翻译成「大脑的工具」。**全项目只有这一个。**

曾经有两个：一个掩码写死成 `location == "SHOP"` 给离线原型用，一个查
`facts["overlay"]` 给真实世界用。那意味着测试里绿的那段掩码代码，真跑时一行都不会
执行——而掩码是这套设计里唯一真正的策略层。离线那套已随 MockWorld 一起删除。

掩码规则：从 `facts["overlay"]` 查 `OVERLAY_ACTIONS`。
**掩码是策略，所以在 harness；`overlay` 是感知的产物，所以由 world 交出来。**
两边通过 `Observation.facts` 这个公开字段衔接，谁也不认识谁的内部。

`overlay` 在熔断里 23/23 全对，是整条感知链里最可靠的一维——把动作空间挂在它上面
是刻意的：分类错一次的代价是大脑看到一组不该有的动作，比字段读错严重得多。

## 还没做的

- **记忆检索仍是字符集重叠**。换向量检索是机制一的事，
  现在换会掩盖「检索策略属于实现方」这个分层是否成立。
- **六件套只有 trace 一件**：缺权限确认、沙箱、成本上限、checkpoint、replay。
"""

from __future__ import annotations

import json

from pokemon_agent.harness.judge import LLMSuccessJudge
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.interfaces.world import WorldPort
from pokemon_agent.schemas.core import (
    OVERLAY_ACTIONS,
    Action,
    ActionSpace,
    EpisodeOutcome,
    EventType,
    MemoryEntry,
    Observation,
    Overlay,
    Source,
    Task,
    ToolResult,
    terrain_legend,
)

BUTTON_HELP: dict[Overlay, dict[str, str]] = {
    Overlay.NONE: {
        "up": "向上走一格", "down": "向下走一格",
        "left": "向左走一格", "right": "向右走一格",
        "a": "与面前的人或物互动（调查、对话、开门）",
        "start": "打开主菜单",
    },
    Overlay.DIALOG: {"a": "推进对话到下一句"},
    Overlay.CHOICE: {
        "up": "光标上移一项", "down": "光标下移一项",
        "a": "选中光标所在项", "b": "取消，退回上一层",
    },
}
"""同一个键在不同 overlay 下含义不同，说明也得跟着变。

`a` 在野外是「互动」、在对话框里是「推进」、在选择框里是「确认」——
给大脑一份放之四海的说明，等于让它自己去猜当前语境。
"""

MAP_HINT = (
    "## 怎么读 walk_map\n"
    "已知事实里的 `walk_map` 是一张 10 列 x 9 行的地图，"
    "**它来自模拟器内存，不是看出来的，100% 准确**：\n"
    + terrain_legend() + "\n"
    "\n"
    "## 两套坐标，别混\n"
    "已知事实里有两种坐标，写法不同，含义完全不同：\n"
    "- **屏幕格 `(列,行)`** —— `walk_map` 的行列号、`landmarks` 里的坐标，都是这种。\n"
    "  它描述的是**这一帧画面上的位置**。画面永远跟着你走，所以**你在屏幕格里恒为 (4,4)**，\n"
    "  走一步之后同一个 `(3,4)` 指的已经是另一块地方了。**它不能跨步骤引用。**\n"
    "- **全局坐标 `x= y=`** —— 已知事实里的 `where`，还带着地图编号。\n"
    "  它描述的是**你在整张地图上的位置**，走一步它就变一格。\n"
    "  判断「我这一步到底动没动」「我是不是在原地打转」，只能看它。\n"
    "\n"
    "一句话：**要按哪个键看屏幕格，要判断自己有没有进展看全局坐标。**\n"
    "\n"
    "四个方向键各自通往哪一格（屏幕格）：\n"
    "  up -> (4,3)    down -> (4,5)    left -> (3,4)    right -> (5,4)\n"
    "\n"
    "怎么用：\n"
    "- 目标格是 `#` 就别按，按了只会原地转向，白花一步。\n"
    "- `D` 是门，走进去就换地图；进屋、上下楼都靠它。\n"
    "- `N` 和 `S` **走不过去，但值得靠近**：先按方向键转向它（人不会让路），"
    "再按 A 对话或查看。任务里要找谁说话，就是找 `N`。\n"
    "- `G` 能走，但走进去可能触发野生宝可梦战斗。赶路时能绕就绕。\n"
    "\n"
    "`landmarks` 是视觉模型补的名字（哪栋房子是宝可梦中心），**它可能有错**；"
    "地图不会错。两者矛盾时信地图。\n"
    "\n"
    "地图是**这一帧**的，走一步就会整个变。不要拿上一步的地图推理这一步。"
)
"""怎么读地图。

**坐标从 `PLAYER_CELL` 生成，不手写**：感知说的 (4,3) 和大脑理解的 (4,3) 必须是
同一格，对不上不会报错，只会静默错位。

这一版之前，通行图是视觉模型读出来的，试了三轮都不行——墙认成门、窗户认成人。
现在它直接读模拟器内存（`world/ram.py`），抄的是游戏自己的碰撞判定，
**几何这一维从 87% 变成 100%**，而且不要钱、零延迟。
视觉模型只负责在这张正确的骨架上标语义，那是它擅长的。

所以这一段最要紧的是把两者的可信度差别讲清楚：`walk_map` 不会错，`landmarks` 会。
不讲清楚的话，模型又会像上一版那样，为了自圆其说去编一个"门是特殊格"出来。

最后一句有来历：更早一版里模型把 `north: grass x3` 当成了**跨步骤的额度**
（"我按过 3 次了，用完了"），在这上面写了 700 token 的自我拉扯。
地图是每帧重出的，这件事必须说明白。
"""

REPEAT_HINT = (
    "## 怎么用连按\n"
    "用 `\"args\": {\"times\": \"N\"}` 连按同一个键，N 最多 8。\n"
    "**每一步都要花一次感知调用。** 一条直线拆成五步走，就是把同一段路的成本乘以五，"
    "而且中间那四次观测你什么新东西都不会看到。\n"
    "**规则：先在 walk_map 上把路径规划到转弯处，再把开头那段同方向的一次走完。**\n"
    "  例：路径是 left, left, down —— 开头两个都是 left，"
    "所以这一步选 `left` 且 `times` 填 `2`；下一步再选 `down`。\n"
    "  例：路径是 up, right —— 开头只有一个 up，`times` 填 `1`。\n"
    "N 直接从 walk_map 上数：沿那个方向连续有几个 `.`，数到 `#`、`?` 或要转弯的那格为止。\n"
    "只有一种情况该主动放弃连按：目标格是 `?`，或者你预期中途会触发对话、遭遇战。"
)
"""连按提示。

随动作空间下发而不是写进 prompt 模板，因为它是**动作接口的一部分**——
模型能不能用 `times` 取决于 harness 认不认，和 prompt 怎么写无关。

## 为什么要写成规则加例子，而不是只说"可以连按"

实测：模型已经把路径算对了（`(4,4)→left→(3,4)→left→(2,4)→down→(2,5)`），
却仍然只走第一步。它不是不会用 `times`，是**没有理由用**——
"可以连按"是一句许可，许可不会改变行为。

所以这里给的是三样东西：**代价**（每步一次感知调用）、**规则**（把开头同向的一段
合并）、**例子**（left,left,down → `left ×2`）。例子最要紧，它把规则落在
模型自己刚写出来的那种路径上。

反过来，"什么时候不该连按"也要写明（目标是 `?`、预期中途有事件），
否则收紧一处会在另一处过度放开。


**放 `ActionSpace.note` 而不是 `descriptions`**：`_build_prompt` 只遍历 `names`
渲染说明，塞进 descriptions 的额外键永远不会被渲染出去——写了等于没写。
"""


class Harness:
    """有状态的中间层。铁律 1 说的是大脑无状态，状态本来就该集中在这里。"""

    def __init__(
        self, world: WorldPort, trace: TracePort, judge: LLMSuccessJudge | None = None
    ) -> None:
        """`judge` 可以不传——不传就永远判"未达成"，episode 只会因步数用尽而结束。

        判定放在 harness 而不是 world，有两个理由：world 不该认识 LLM；
        而且判定必须进 trace（要能统计它的成本和失效），TracePort 只有这一层有。
        """
        self._world = world
        self._trace = trace
        self._judge = judge
        self._succeeded = False
        self._why = ""

        self._episode_id = ""
        self._task: Task | None = None
        self._memories: list[MemoryEntry] = []
        self._last_space: ActionSpace | None = None
        self._last_step: int | None = None
        # 每步只记一次 OBSERVE。perceive() 一步里会被调用多次（observe 节点、
        # act 节点的兜底），不去重的话同一个观测会重复出现在事件流里。
        self._traced_step: int | None = None
        self._judged_step: int | None = None
        """已经判过的那一步。

        判定要花钱，而**一步之内不会有两个不同的答案**——同一帧问两次是纯浪费。
        没有它的时候实测每步判两次：`execute()` 之后一次，下一轮 `perceive()` 又一次。
        """

    # ---- episode 生命周期 ----

    def start_episode(self, episode_id: str, task: Task) -> Observation:
        """开一个新 episode。记忆**不清空**——跨任务复用经验正是要验证的东西。"""
        assert episode_id, "start_episode() got an empty episode_id"

        self._episode_id = episode_id
        self._task = task
        self._last_space = self._last_step = None

        self._traced_step = self._judged_step = None
        self._succeeded, self._why = False, ""
        obs = self._world.reset(task)

        # **episode 的边界必须进事件流。** 没有它，光看日志分不出一次尝试从哪开始，
        # 更不知道它带了多少条记忆进来——而那正是 A/B 实验的自变量本身。
        self._trace.append(
            episode_id, 0, EventType.EPISODE_START, Source.HARNESS,
            {"task_id": task.task_id, "goal": task.goal,
             "max_steps": str(task.max_steps),
             "memory_carried": str(len(self._memories))},
        )
        # 开局这一帧也要走 settle：**任务可能一开始就已经达成**
        # （比如起点存档就站在母亲面前）。不判的话这种 episode 会白跑满步数，
        # 而成功率里少掉的正是最容易达成的那些——统计会被系统性地压低。
        obs = self.settle(obs)

        assert obs.step == 0, "a new episode must start at step 0"
        return obs

    def outcome(self, obs: Observation) -> EpisodeOutcome:
        assert obs.done, "outcome() called before the episode finished"
        assert self._task is not None, "outcome() before start_episode()"

        reason = ("success" if obs.success
                  else "max_steps_exceeded" if obs.step >= self._task.max_steps
                  else "failed")
        result = EpisodeOutcome(
            episode_id=self._episode_id, task_id=self._task.task_id,
            success=obs.success, steps=obs.step, reason=reason,
        )
        # **成功与否必须落进事件流。** 不记的话，光看日志算不出成功率——
        # 而那是这个项目唯一的一组硬数字。
        self._trace.append(
            self._episode_id, obs.step, EventType.EPISODE_END, Source.HARNESS,
            {"success": str(result.success), "steps": str(result.steps),
             "reason": result.reason, "task_id": result.task_id,
             # 判定给的理由要留档：成功率是要报的数字，**每一个 True 都得说得出依据**
             "why": self._why},
        )
        return result

    # ---- ToolPort ----

    def perceive(self) -> Observation:
        assert self._task is not None, "perceive() before start_episode()"

        return self.settle(self._world.observe())

    def settle(self, obs: Observation) -> Observation:
        """把一次观测记进 trace 并交给判定器，**每步只做一次**。

        单独成一个方法而不是塞进 `execute()`，是为了让事件流的步号单调。

        `act` 节点一轮里会产出**两个步**的事件：`ACT` 和 `MEMORY_WRITE` 属于第 N 步，
        而执行后的观测属于第 N+1 步。`execute()` 里就把新观测记掉的话，顺序变成
        `ACT(N) → OBSERVE(N+1) → MEMORY_WRITE(N)`——步号往回跳，读日志的人会
        把那条记忆读成下一步的。现在由调用方在写完记忆之后再调，顺序才是
        `ACT(N) → MEMORY_WRITE(N) → OBSERVE(N+1)`。
        """
        assert self._task is not None, "settle() before start_episode()"

        self._trace_observe(obs)
        return self._check_success(obs)

    def _check_success(self, obs: Observation) -> Observation:
        """问判定器：任务达成了没有。达成就把 `done` / `success` 覆写上去。

        **world 只按步数终止**，达成与否它不知道也不该知道。所以这一步是
        harness 在 world 给出的观测上**加一层结论**，图的 `should_continue`
        读的就是被覆写后的 `done`。

        两处不问：
        - 一步之内问过了。判定要花钱，而同一帧不会有两个答案。
        - 已经判过成功。结论不会反悔——"已经和母亲说过话了"这件事，
          不会因为多走一步就变回没说过。

        **`obs.done` 不是跳过的理由。** 那里的 `done` 是"步数用尽"，
        而任务完全可能恰好在最后一步达成。见 done 就不判的话，这类 episode
        会被记成 max_steps_exceeded——**成功率被系统性地压低，而且是往难看的方向偏**。
        """
        if self._judge is None or self._succeeded:
            return obs
        if self._judged_step == obs.step:
            return obs
        self._judged_step = obs.step
        assert self._task is not None

        verdict = self._judge.judge(self._task, obs)
        # **判定的账单单独记。** 它和决策各自烧 token，混在一起就说不清
        # "成功率这个数字本身花了多少钱"，也算不出判定器自己的失效率。
        self._trace.append(
            self._episode_id, obs.step, EventType.MODEL_CALL, Source.JUDGE, verdict.call
        )
        if not verdict.done:
            return obs

        self._succeeded, self._why = True, verdict.why
        return obs.model_copy(update={"done": True, "success": True})

    def get_action_space(self) -> ActionSpace:
        """掩码发生在这里，**只看 overlay**。

        后置条件：names 非空。走投无路也必须给至少一个动作——
        空动作空间是 harness 的 bug，不能推给大脑处理。
        """
        obs = self._world.observe()
        overlay = Overlay(obs.facts.get("overlay", Overlay.NONE.value))
        names = [a for a in OVERLAY_ACTIONS[overlay] if a in self._world.all_actions()]

        assert names, f"action space must never be empty (overlay={overlay})"
        space = ActionSpace(
            names=names,
            descriptions=dict(BUTTON_HELP[overlay]),
            note=f"{MAP_HINT}\n\n{REPEAT_HINT}",
        )
        self._last_space, self._last_step = space, obs.step
        return space

    def execute(self, action: Action) -> ToolResult:
        """执行动作。

        前置条件：调用方必须先调用过 get_action_space()，且 action 来自那次结果。
        """
        assert self._last_space is not None, "execute() before get_action_space()"
        assert self._last_space.contains(action.name), (
            f"execute() got {action.name!r} outside {self._last_space.names}"
        )
        assert self._last_step is not None, "_last_step must be set with _last_space"

        step_before = self._last_step
        result = self._world.step(action)
        self._trace.append(
            self._episode_id, step_before, EventType.ACT, Source.WORLD,
            {"action": action.name, "args": json.dumps(action.args, ensure_ascii=False),
             "message": result.message},
        )
        # **不在这里记新观测。** 记了的话，下一步的 OBSERVE 会先于本步的
        # MEMORY_WRITE 出现在事件流里，读起来像是记忆属于下一步。
        # 观测统一由 perceive() 记，事件顺序就是
        # observe → recall → think → act → memory。

        self._last_space = self._last_step = None   # 世界推进了，上次的空间失效

        # **不在这里记新观测。** 它属于下一步，而这一步的 MEMORY_WRITE 还没写。
        # 调用方写完记忆后调 `settle()`，事件流的步号才单调。
        return result

    def memory_query(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """本阶段是朴素的字符重叠打分。**检索策略属于实现方**，签名不变。

        ## 它现在几乎不筛，这一点要知道

        中文条目里"的、了、是、在、边"这类字随处都有，任意两条中文文本的重叠数
        几乎恒大于零。实测查"北边是草丛"，一条讲"南边有水面"的记忆也会被选中——
        只因为共用了一个"边"字。排序还是对的（相关那条重叠数明显更高），
        但**筛选形同虚设**，实际效果接近"按 step 倒序返回最近 N 条"。

        为什么写在这里：做「有记忆 vs 无记忆」的 A/B 时，很容易把
        "最近 N 条也有用"误读成"检索有用"——那是两个完全不同的结论。
        机制一（状态归并 + 向量检索）要换掉的就是这个方法体。
        """
        assert limit > 0, f"limit must be > 0, got {limit}"

        # 打分对着 `render()` 的文本，**和喂进 prompt 的是同一份**。
        # 分成两份的话，可能出现"按 A 的内容选中，却把 B 的内容喂进去"，而且不报错。
        scored = sorted(self._memories, key=lambda m: (self._overlap(query, m.render()), m.step),
                        reverse=True)
        hits = [m for m in scored if self._overlap(query, m.render()) > 0][:limit]

        assert len(hits) <= limit, "memory_query must respect the limit"
        return hits

    def memory_write(self, entry: MemoryEntry) -> None:
        assert entry.rationale, "memory_write() got an entry without a rationale"
        self._memories.append(entry)

    # ---- 内部 ----

    def _trace_observe(self, obs: Observation) -> None:
        """把观测连同**感知开销**一起记下来。每步只记一次。

        `source` 标明是感知产生的：感知和决策各自烧 token，不标来源就拆不开两笔账，
        而「感知走便宜模型、决策走强模型」这个成本叙事全靠这个拆分。
        """
        if obs.step == self._traced_step:
            return
        self._traced_step = obs.step

        # **模型调用在前，观测在后 —— 这是因果顺序，不是排版偏好。**
        # 那几次调用产出 `ScreenState`，观测才拼得出来。反过来记的话，
        # 拿事件流做 replay 或离线重算的人会先看到结果、再看到产生它的原因。
        # 控制台上"成本行跑到 step 表头上面"是**显示层的问题**，在显示层解决
        # （`probe/echo_trace.py` 自己记一份"这一步的表头打过没有"）。
        # 不能为了排版好看去改事件流——trace 是这套系统里唯一的事实来源。
        for call in self._world.last_calls:
            self._trace.append(
                self._episode_id, obs.step, EventType.MODEL_CALL, Source.PERCEPTION, call
            )

        self._trace.append(
            self._episode_id, obs.step, EventType.OBSERVE, Source.PERCEPTION,
            # **facts 必须进 payload。** 它才是观测的实质内容。只记 summary 的话，
            # replay 出来只剩「你在野外」这种废话，既看不出大脑当时掌握了什么，
            # 也没法回答「决策错是因为没看见还是没想到」。
            #
            # `frame_sha` 同样关键：没有它，一条读错的观测**无法追查**是哪一帧，
            # 阶段 3.2 拿 VLM 输出和真值对标也对不上号。
            {"frame_sha": self._world.last_frame_sha,
             "summary": obs.summary,
             "scene": obs.facts.get("scene", ""), "overlay": obs.facts.get("overlay", ""),
             "facts": json.dumps(obs.facts, ensure_ascii=False)},
        )

    @staticmethod
    def _overlap(query: str, content: str) -> int:
        return len(set(query) & set(content))
