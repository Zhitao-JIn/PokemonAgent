"""MockWorld —— 一个极简的格子世界，实现 WorldPort。

**它不是游戏**，只是一个能被推进、能被观测、能判定任务成败的状态机。
存在的意义是让上层跑起来，将来换成真实模拟器时它会被删掉。

地图（一条直线，够用了）：
    HOME ── ROUTE ── SHOP ── GYM
道具 potion 掉在 ROUTE，GYM 里有个馆主。

刻意保留的两个特性，因为上层需要它们才能被测到：
- **动作会失败**（没买药就挑战馆主 → ok=False），用来测"合法但没成功"这条分支。
- **动作空间随位置变化**（只有在 SHOP 才能 buy），这是 masking 的数据来源。
"""

from __future__ import annotations

from pokemon_agent.schemas.core import Action, Observation, Task, ToolResult

_MAP: list[str] = ["HOME", "ROUTE", "SHOP", "GYM"]

_ALL_ACTIONS: list[str] = ["move_forward", "move_back", "pick_up", "buy_potion", "fight_gym"]

_ACTION_DESCRIPTIONS: dict[str, str] = {
    "move_forward": "向前走一格",
    "move_back": "向后退一格",
    "pick_up": "捡起当前位置的道具",
    "buy_potion": "在商店购买一瓶药水",
    "fight_gym": "挑战道馆馆主（没有药水会输）",
}


class MockWorld:
    """一维格子世界。状态全在实例变量里——**世界当然是有状态的**，无状态的是大脑。"""

    def __init__(self) -> None:
        self._task: Task | None = None
        self._position = 0
        self._step = 0
        self._has_potion = False
        self._potion_on_ground = True
        self._gym_cleared = False
        self._done = False
        self._success = False

    # ---- WorldPort ----

    def reset(self, task: Task) -> Observation:
        """按任务重置。

        前置条件：task.max_steps > 0。
        后置条件：step == 0、done 为 False、goal == task.goal。
        """
        assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"

        self._task = task
        self._position = 0
        self._step = 0
        self._has_potion = False
        self._potion_on_ground = True
        self._gym_cleared = False
        self._done = False
        self._success = False

        obs = self.observe()
        assert obs.step == 0 and not obs.done, "reset() must return a fresh observation"
        assert obs.goal == task.goal, "reset() must echo the task goal"
        return obs

    def observe(self) -> Observation:
        """只读，不推进世界。

        前置条件：已调用过 reset()。
        """
        assert self._task is not None, "observe() before reset()"

        place = _MAP[self._position]
        return Observation(
            step=self._step,
            goal=self._task.goal,
            summary=self._describe(place),
            facts={
                "location": place,
                "has_potion": str(self._has_potion),
                "gym_cleared": str(self._gym_cleared),
                "steps_left": str(self._task.max_steps - self._step),
            },
            done=self._done,
            success=self._success,
        )

    def all_actions(self) -> list[str]:
        """全部动作，与状态无关。masking 是 harness 的事，不在这里做。"""
        return list(_ALL_ACTIONS)

    def step(self, action: Action) -> ToolResult:
        """执行动作并推进世界。

        前置条件：action.name 在 all_actions() 中；当前 episode 未结束。
        后置条件：返回的 observation.step == 调用前 + 1；
            达成判据或用满 max_steps 时 done 为 True。
        """
        assert self._task is not None, "step() before reset()"
        assert action.name in _ALL_ACTIONS, f"unknown action {action.name!r}"
        assert not self._done, "step() called on a finished episode"

        before = self._step
        ok, message = self._apply(action.name)
        self._step += 1

        # 成败判定属于 world：只有它知道游戏状态是否满足判据（见 WorldPort 契约）。
        if self._gym_cleared:
            self._done, self._success = True, True
        elif self._step >= self._task.max_steps:
            self._done, self._success = True, False

        obs = self.observe()
        assert obs.step == before + 1, "step() must advance exactly one step"
        return ToolResult(ok=ok, message=message, observation=obs)

    # ---- 内部 ----

    def _apply(self, name: str) -> tuple[bool, str]:
        """执行动作的实际效果。返回 (是否成功, 给 LLM 读的描述)。

        失败一律走返回值而不是异常：动作合法但没成功是**预期内的游戏事件**。
        """
        if name == "move_forward":
            if self._position >= len(_MAP) - 1:
                return False, "前面没路了"
            self._position += 1
            return True, f"你走到了 {_MAP[self._position]}"

        if name == "move_back":
            if self._position <= 0:
                return False, "后面没路了"
            self._position -= 1
            return True, f"你退回到 {_MAP[self._position]}"

        if name == "pick_up":
            if _MAP[self._position] != "ROUTE" or not self._potion_on_ground:
                return False, "这里没有东西可捡"
            self._potion_on_ground = False
            self._has_potion = True
            return True, "你捡起了一瓶药水"

        if name == "buy_potion":
            if _MAP[self._position] != "SHOP":
                return False, "这里不是商店"
            self._has_potion = True
            return True, "你买到了一瓶药水"

        if name == "fight_gym":
            if _MAP[self._position] != "GYM":
                return False, "这里不是道馆"
            if not self._has_potion:
                return False, "你没有药水，被馆主打败了"
            self._gym_cleared = True
            return True, "你击败了馆主，任务完成"

        raise AssertionError(f"unhandled action {name!r}")  # pragma: no cover

    def _describe(self, place: str) -> str:
        bits = [f"你在 {place}。"]
        if place == "ROUTE" and self._potion_on_ground:
            bits.append("地上有一瓶药水。")
        if place == "SHOP":
            bits.append("店员在柜台后面。")
        if place == "GYM":
            bits.append("馆主正在等你挑战。")
        bits.append("你带着药水。" if self._has_potion else "你没有药水。")
        return "".join(bits)


# 原型期的默认任务。它满足 Task 的下界要求吗？——不满足，它太短了。
# 保留它只是为了让最小闭环跑起来；真实任务集要按 Task docstring 的标准另行设计。
DEMO_TASK = Task(
    task_id="reach-gym-with-potion",
    goal="拿到一瓶药水，然后到道馆击败馆主",
    success_criteria="gym_cleared 为 True",
    max_steps=12,
)

DEMO_ACTION_DESCRIPTIONS = dict(_ACTION_DESCRIPTIONS)
