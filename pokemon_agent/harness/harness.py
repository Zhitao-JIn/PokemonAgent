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
    tile_legend,
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
    "已知事实里的 `walk_map` 是一张 10 列 x 9 行的地形图，图例：\n"
    + tile_legend() + "\n"
    "**你永远在 (4,4)。** 四个方向键各自通往哪一格：\n"
    "  up -> (4,3)    down -> (4,5)    left -> (3,4)    right -> (5,4)\n"
    "按方向键之前先看目标格的符号，照图例判断。\n"
    "走不过去的格子**按了只会原地转向**——但转向不是白费：`N` 和 `S` 要先面朝它，"
    "才能按 A 对话或调查。\n"
    "`?` 别算进连按，想去就单独按一步试。\n"
    "地图是**这一帧**的，走一步就会整个变。不要拿上一步的地图推理这一步。\n"
    "\n"
    "## 三样东西打架时信谁\n"
    "已知事实里关于画面的有三样，可信度从高到低：**`overview` > `walk_map` > `landmarks`**。\n"
    "越粗的判断越可靠——「左下角是房子」比「(2,6) 这一格是墙」好判断得多，"
    "而 `landmarks` 是最细的一层，最容易认错。\n"
    "所以：`overview` 说那边是一整片水，而 `walk_map` 在那片里给了一格 `.`，"
    "**按 `?` 对待**，别把它当成一条捷径。"
)
"""怎么读地图。

**图例从 `TILES` 生成，坐标从 `PLAYER_CELL` 生成，一个字都不手写。**
感知 prompt 用的是同一个 `tile_legend()`。两边任何一处对不上，模型和大脑就在用
两套字典——而这种错不会报错，只会静默地互相误解。

这一版之前，通行性是模型直接给的一个 bit，于是出现过：它认出了门、
却因为门看着像墙标了 `#`，大脑再花 765 个 token 编出「门是特殊格」来自圆其说。
现在模型只报地形，能不能走由 `TILES` 算——**规则回到我们手里，也就不需要例外了**。

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

    def __init__(self, world: WorldPort, trace: TracePort) -> None:
        self._world = world
        self._trace = trace

        self._episode_id = ""
        self._task: Task | None = None
        self._memories: list[MemoryEntry] = []
        self._last_space: ActionSpace | None = None
        self._last_step: int | None = None
        # 每步只记一次 OBSERVE。perceive() 一步里会被调用多次（observe 节点、
        # act 节点的兜底），不去重的话同一个观测会重复出现在事件流里。
        self._traced_step: int | None = None

    # ---- episode 生命周期 ----

    def start_episode(self, episode_id: str, task: Task) -> Observation:
        """开一个新 episode。记忆**不清空**——跨任务复用经验正是要验证的东西。"""
        assert episode_id, "start_episode() got an empty episode_id"

        self._episode_id = episode_id
        self._task = task
        self._last_space = self._last_step = None

        self._traced_step = None
        obs = self._world.reset(task)

        # **episode 的边界必须进事件流。** 没有它，光看日志分不出一次尝试从哪开始，
        # 更不知道它带了多少条记忆进来——而那正是 A/B 实验的自变量本身。
        self._trace.append(
            episode_id, 0, EventType.EPISODE_START, Source.HARNESS,
            {"task_id": task.task_id, "goal": task.goal,
             "max_steps": str(task.max_steps),
             "memory_carried": str(len(self._memories))},
        )
        self._trace_observe(obs)

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
             "reason": result.reason, "task_id": result.task_id},
        )
        return result

    # ---- ToolPort ----

    def perceive(self) -> Observation:
        assert self._task is not None, "perceive() before start_episode()"

        obs = self._world.observe()
        self._trace_observe(obs)
        return obs

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
             "ok": str(result.ok), "message": result.message},
        )
        # **不在这里记新观测。** 记了的话，下一步的 OBSERVE 会先于本步的
        # MEMORY_WRITE 出现在事件流里，读起来像是记忆属于下一步。
        # 观测统一由 perceive() 记，事件顺序就是
        # observe → recall → think → act → memory。

        self._last_space = self._last_step = None   # 世界推进了，上次的空间失效
        return result

    def memory_query(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """本阶段是朴素的字符重叠打分。**检索策略属于实现方**，签名不变。"""
        assert limit > 0, f"limit must be > 0, got {limit}"

        scored = sorted(self._memories, key=lambda m: (self._overlap(query, m.content), m.step),
                        reverse=True)
        hits = [m for m in scored if self._overlap(query, m.content) > 0][:limit]

        assert len(hits) <= limit, "memory_query must respect the limit"
        return hits

    def memory_write(self, entry: MemoryEntry) -> None:
        assert entry.content, "memory_write() got an empty entry"
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

        # 感知的每一次模型调用各记一条，失败的也记 —— 它们同样烧了 token，
        # 而 `raw` 让解析器改进后能离线重算，不必重新花钱调 API。
        for call in self._world.last_calls:
            self._trace.append(
                self._episode_id, obs.step, EventType.MODEL_CALL, Source.PERCEPTION, call
            )

        self._trace.append(
            self._episode_id, obs.step, EventType.OBSERVE, Source.PERCEPTION,
            # **facts 必须进 payload。** 它才是观测的实质内容——四个方向、landmarks、
            # 战斗双方状态。只记 summary 的话，replay 出来只剩「你在野外」这种废话，
            # 既看不出大脑当时掌握了什么，也没法回答「决策错是因为没看见还是没想到」。
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
