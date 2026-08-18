"""MockHarness —— ToolPort 的替身实现。

**它是 mock。** 当前阶段只有大脑是真的；这个类的存在是为了让大脑有东西可调。
它离真正的 harness 差得很远：

- masking 是写死的 if 分支，不是从状态表查（机制一）
- 记忆检索是字符集重叠打分，没有 state abstraction，没有值回填（机制三）
- 六件套只有 trace 一件，缺权限确认、沙箱、成本控制、checkpoint、replay
- 动作空间不会增长，没有 skill library（机制二）

但它**严格遵守 ToolPort 的契约**——替身可以简陋，不能违约，否则换成真实 harness 时上层会崩。

职责边界（这两条在真实实现里也一样，写在这里免得后面搞错）：
- **masking 在 harness，不在 world**。掩码是策略：什么时候允许买东西是设计决定，
  不是世界的固有能力。
- **成败判定在 world，不在 harness**。只有世界知道游戏状态是否满足判据。
"""

from __future__ import annotations

from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.interfaces.world import WorldPort
from pokemon_agent.schemas.core import (
    Action,
    ActionSpace,
    EpisodeOutcome,
    EventType,
    MemoryEntry,
    Observation,
    Task,
    ToolResult,
)


class MockHarness:
    """把"世界的能力"翻译成"大脑的工具"。

    它**有状态**（当前 episode、记忆、最近一次给出的动作空间），这是对的——
    铁律 1 说的是大脑无状态，状态本来就该集中在这里。
    """

    def __init__(
        self,
        world: WorldPort,
        trace: TracePort,
        *,
        action_descriptions: dict[str, str] | None = None,
    ) -> None:
        """依赖注入：world 和 trace 都是接口类型，不知道具体是谁。"""
        self._world = world
        self._trace = trace
        self._descriptions = dict(action_descriptions or {})

        self._episode_id = ""
        self._task: Task | None = None
        self._memories: list[MemoryEntry] = []
        # 记住最近一次给出的动作空间，用来在 execute() 里执行 precondition。
        self._last_space: ActionSpace | None = None
        # 以及那次动作空间是在哪一步给出的——ACT 事件要用它，
        # 才能和同一步的 THINK / COST 落在同一个 step 上。两者同生同灭。
        self._last_step: int | None = None

    # ---- episode 生命周期（harness 自己的接口，不属于 ToolPort）----

    def start_episode(self, episode_id: str, task: Task) -> Observation:
        """开一个新 episode。

        前置条件：episode_id 非空。
        后置条件：返回 step == 0 的观测。
        注意记忆**不清空**：跨任务尝试复用经验正是这套架构想验证的东西。
        """
        assert episode_id, "start_episode() got an empty episode_id"

        self._episode_id = episode_id
        self._task = task
        self._last_space = None
        self._last_step = None

        obs = self._world.reset(task)
        self._trace.append(episode_id, obs.step, EventType.OBSERVE, {"summary": obs.summary})

        assert obs.step == 0, "a new episode must start at step 0"
        return obs

    def outcome(self, obs: Observation) -> EpisodeOutcome:
        """把终止观测转成结构化结果。

        前置条件：obs.done 为 True。调用方要先确认 episode 结束了。
        """
        assert obs.done, "outcome() called before the episode finished"
        assert self._task is not None, "outcome() before start_episode()"

        if obs.success:
            reason = "success"
        elif obs.step >= self._task.max_steps:
            reason = "max_steps_exceeded"
        else:
            reason = "failed"

        return EpisodeOutcome(
            episode_id=self._episode_id,
            task_id=self._task.task_id,
            success=obs.success,
            steps=obs.step,
            reason=reason,
        )

    # ---- ToolPort：大脑能力的全集 ----

    def perceive(self) -> Observation:
        """取当前观测。只读，幂等。"""
        assert self._task is not None, "perceive() before start_episode()"

        obs = self._world.observe()
        assert obs.goal == self._task.goal, "observation goal must match the running task"
        return obs

    def get_action_space(self) -> ActionSpace:
        """当前状态下可用的动作（masking 发生在这里）。

        后置条件：names 非空。走投无路也必须给出至少一个动作——
        空动作空间是 harness 的 bug，不能推给大脑处理。
        """
        obs = self._world.observe()
        names = [a for a in self._world.all_actions() if self._is_available(a, obs)]

        assert names, "action space must never be empty (see ToolPort contract)"
        space = ActionSpace(
            names=names,
            descriptions={n: self._descriptions.get(n, "") for n in names},
        )
        # 记下来，execute() 的 precondition 要用它。
        # step 一并记住：复用这里已经取到的 obs，不额外调 observe()——
        # 真实模拟器上 observe() 是「截图 + VLM」，为记一条日志再感知一次太贵。
        self._last_space = space
        self._last_step = obs.step
        return space

    def execute(self, action: Action) -> ToolResult:
        """执行动作，推进世界。

        前置条件：调用方**必须先调用过 get_action_space()**，且 action 来自那次结果。
            这两条都 assert：大脑幻觉出不存在的动作会在这里就地爆炸，
            而不是变成一个语义不明的模拟器错误。
        """
        assert self._last_space is not None, "execute() before get_action_space()"
        assert self._last_space.contains(action.name), (
            f"execute() got {action.name!r} outside the action space {self._last_space.names}"
        )

        assert self._last_step is not None, "_last_step must be set together with _last_space"

        result = self._world.step(action)
        self._trace.append(
            self._episode_id,
            # **执行前**的 step，不是执行后的。这一步的 THINK / COST / MEMORY_WRITE
            # 用的都是执行前的值，ACT 必须和它们同桶——否则按 step 聚合时
            # （失败模式统计、replay 重建、单步成本）动作会一律落进下一桶，
            # 不报错，只是悄悄算歪。
            self._last_step,
            EventType.ACT,
            {"action": action.name, "ok": str(result.ok), "message": result.message},
        )
        # 世界推进了，上一次的动作空间随即失效——下一步必须重新问。
        self._last_space = None
        self._last_step = None
        return result

    def memory_query(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """检索相关记忆。

        前置条件：limit > 0。
        后置条件：返回条数 <= limit。

        本阶段是朴素的关键词重叠打分。**检索策略属于实现方**，
        机制一（状态归并）、机制三（值回填）接进来时改的是这个方法体，签名不动。
        """
        assert limit > 0, f"limit must be > 0, got {limit}"

        scored = sorted(
            self._memories,
            key=lambda m: (self._overlap(query, m.content), m.step),
            reverse=True,
        )
        hits = [m for m in scored if self._overlap(query, m.content) > 0][:limit]

        assert len(hits) <= limit, "memory_query must respect the limit"
        return hits

    def memory_write(self, entry: MemoryEntry) -> None:
        """写入一条记忆。

        前置条件：entry.content 非空。
        """
        assert entry.content, "memory_write() got an empty entry"
        self._memories.append(entry)

    # ---- 内部策略 ----

    def _is_available(self, action_name: str, obs: Observation) -> bool:
        """masking 规则。写死在这里是原型期的选择——

        将来这里会变成"从状态表查这个状态的可用动作"，但那时改的是这个方法，
        `get_action_space()` 的签名和大脑的用法都不变。
        """
        location = obs.facts.get("location", "")
        if action_name == "buy_potion":
            return location == "SHOP"
        if action_name == "fight_gym":
            return location == "GYM"
        if action_name == "pick_up":
            return location == "ROUTE"
        return True

    @staticmethod
    def _overlap(query: str, content: str) -> int:
        """字符级重叠计数。粗糙但确定，够原型用。

        故意不引入 embedding：这里换成向量检索是机制一的事，
        现在上会掩盖"检索策略属于实现方"这个分层是否真的成立。
        """
        return len(set(query) & set(content))
