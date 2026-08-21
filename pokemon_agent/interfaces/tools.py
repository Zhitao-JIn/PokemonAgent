"""工具层接口 —— **Harness 伸向环境和记忆的两只手，分开的。**

## 两个协议，因为 Harness 要跟两个不同的东西打交道

    GameToolPort     操作世界：感知、执行、开局、溯源。
    MemoryToolPort   读写记忆：情景记忆 + 语义记忆（object）。

以前只有一个 `ToolHost`（另外还有一个更小的 `ToolPort` 给大脑用），
"感知世界"和"记忆"混在同一个协议里、同一个实现类（`GameTools`）里。

现在**大脑不再持有任何工具实例**——`Brain.choose()` 需要的情景记忆由 Harness
先查好、当参数传进去（见 `interfaces/brain.py`）。大脑不再有机会主动调用
`GameToolPort`/`MemoryToolPort` 的任何方法，`ToolPort` 这个"大脑看到的协议"
也就没有存在的必要了——大脑该看到什么，现在完全由 `choose()`/`judge()`/
`reflect()` 的参数表决定，不再需要一个额外的协议来兜底"它还能主动做什么"。

拆成 `GameToolPort`/`MemoryToolPort` 两个协议而不是一个，是因为它们的实现
本来就该是两个不相关的类（`GameTools` 只碰 `WorldPort`，`MemoryTool` 只碰
`memory/` 包），揉进一个协议会让人以为它们必须由同一个对象同时实现。
`Harness.__init__` 现在收两个参数：`game: GameToolPort` 和 `memory: MemoryToolPort`。

## perceive 是纯读，**它不构成一步**

这一条踩过坑：`perceive()` 曾经既是"给大脑看一眼"，又是"新的一步开始了"。
两种身份对它的期待不一样，于是要靠"这一步我是不是已经记过 trace 了"去调和，
而那个判断本身就是 bug 的温床（实测出现过步号回退、判定重复计费）。

现在它只是查询：不写 trace、不推进世界、不触发判定。
**"一步"的边界由 Harness 定义**，那里只有两个地方会产出新的一步。

## known_objects 现在由 Harness 拼，不是 GameTools

以前 `GameTools.perceive()` 会顺手把语义记忆的 `known_here()` 结果拼进
`facts["known_objects"]`——那要求 `GameTools` 持有一份记忆的引用，
恰恰是这次要拆掉的耦合。现在 `GameToolPort.perceive()` 只管世界，
`facts["known_objects"]` 由 `Harness._observe()` 在拿到 `game.perceive()`
的结果之后，另外调 `memory.known_here(obs)` 拼上去——两个协议各管各的，
组合是 Harness 的活。

## 模型调用记账不再靠 drain_calls

`perceive`/`inspect`/`reset` 曾经返回裸的 `Observation`，模型调用记录另开一个
`drain_calls()` 方法、靠世界内部一个缓冲区攒着给 Harness 单独取——这是典型的
"生产和消费分离，靠可变状态搭桥"，缓冲区清早清晚都能把账算错。

现在这三个方法改成返回 `PerceptionResult`（`observation` + `calls` 两个平行字段），
`execute()` 的 `calls` 就挂在已有的 `ToolResult` 上。调用记录跟着它产生的那次
调用一起，作为普通返回值直接交给 Harness，不需要任何跨调用的状态，也就不存在
"drain 的时机对不对"这一整类 bug。见 `PerceptionResult` 的完整说明。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.action import Action, ActionSpace, ToolResult
from pokemon_agent.schemas.memory_episodic import MemoryEntry
from pokemon_agent.schemas.memory_semantic import ObjectFact
from pokemon_agent.schemas.observation import PerceptionResult
from pokemon_agent.schemas.task import Task


@runtime_checkable
class GameToolPort(Protocol):
    """Harness 用它操作世界：感知、执行、开局、溯源。**不碰任何记忆。**"""

    def perceive(self) -> PerceptionResult:
        """取当前观测。**幂等只读**：不推进世界、不写 trace、不触发判定。

        后置条件：同一帧内多次调用**不产生额外的模型调用**（实现方要在帧内缓存——
            感知是每步都要付钱的那一项）；`result.calls` 是这次调用产生的模型调用
            记录，命中缓存时为空列表（**不是 None**）。

        返回的 `observation` 在同一帧内也是稳定的，**除非期间调用过 `inspect()`**：
        那会往 facts 里加一条 `inspected`。这是刻意的（细看的答案要能被下一轮读到），
        但它意味着"幂等"只对模型调用成立，对返回值不成立。
        """
        ...

    def inspect(self, focus: str) -> PerceptionResult:
        """对同一帧再问一次感知，问一个具体的问题。**世界不推进。**

        前置条件：focus 非空。**没有具体问题就不该调它**——
            那样它只是把同一帧原样再看一遍（`perceive()` 帧内缓存，字节完全一样），
            不产生任何新信息，纯粹白烧一次调用。
        后置条件：答案并进下一次 `perceive()` 的 facts；`execute()` 之后自动失效；
            `result.calls` 是这次细看产生的调用记录。
        失败：不抛异常，把"没看清"写成答案。
        """
        ...

    def get_action_space(self) -> ActionSpace:
        """取当前状态下可用的按键（含 masking）。

        后置条件：`names` 非空。走投无路的状态也必须至少给一个动作——
            空动作空间是工具层的 bug，不能让大脑去处理这种情况。

        注意 `intents` **不由这一层填**：能不能拆子目标取决于目标栈有多深，
        那是循环的事。工具层只管按键。
        """
        ...

    def execute(self, action: Action) -> ToolResult:
        """执行一个动作，推进世界。

        前置条件：`action.name` 属于**调用前最近一次** `get_action_space()` 的结果。
            实现方必须 assert 这一点——大脑幻觉出不存在的动作要在这里就地爆炸，
            而不是变成一个语义不明的模拟器错误。
        后置条件：`result.observation` 非空，是执行后的新观测。
            它的 `step` **还没有盖章**——盖章是 Harness 的事。
            `result.calls` 是推进这一步期间产生的模型调用记录（通常来自
            推进后重新感知那一次），命中缓存时为空列表。
        """
        ...

    def reset(self, task: Task) -> PerceptionResult:
        """按任务重置到初始状态并返回首个观测。

        前置条件：`task.max_steps > 0`。
        后置条件：`result.observation.done` 为 False；`step` 未盖章（由 Harness 填 0）；
            `result.calls` 是这次重置期间产生的模型调用记录。
        """
        ...

    @property
    def last_frame_sha(self) -> str:
        """最近一次观测所依据的那一帧的哈希。

        没有它，一条读错的观测**无法追查是哪一帧**——而那是查感知错误的起点。
        没有"帧"这个概念的实现返回空串。
        """
        ...


@runtime_checkable
class MemoryToolPort(Protocol):
    """Harness 用它读写记忆：情景记忆 + 语义记忆（object）。**不碰世界。**

    两类记忆分开暴露，因为它们的读写语义不同：情景记忆按相似度/时间检索，
    语义记忆按坐标查。程序记忆（procedural）还没做，先不占位。
    """

    # ---- 情景记忆：episodic ----

    def query_episodic(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """检索相关的情景记忆。

        前置条件：limit > 0。
        后置条件：返回条数 <= limit；按相关性降序。
            **检索策略属于实现方**——调用方不知道也不该知道记忆从哪来、怎么排的。
        """
        ...

    def recent(self, episode_id: str, limit: int) -> list[MemoryEntry]:
        """**这一局**最近几条情景记忆，按时间顺序。

        前置条件：limit > 0。
        后置条件：返回条数 <= limit；全部来自 `episode_id` 这一局；最新的在最后。
        """
        ...

    def write_episodic(self, entry: MemoryEntry) -> None:
        """写入一条情景记忆。

        前置条件：`entry.rationale` 非空。没有理由的经验取回来也没用——
            它说不出当时为什么这么判断，也就无法检查那个判断现在还成不成立。
        """
        ...

    @property
    def episodic_size(self) -> int:
        """库里有多少条情景记忆。**A/B 实验的自变量之一**，要能被记进事件流。"""
        ...

    # ---- 语义记忆：object ----

    def known_here(self, obs: Observation) -> str:
        """`obs.place` 所在地图上，已知的语义记忆（object）渲染成的一段文字。

        后置条件：`obs.place` 为 None 时返回空串；没有任何已知条目时也返回空串——
            调用方（Harness）据此决定要不要往 `facts["known_objects"]` 里塞东西。
        """
        ...

    def see_objects(self, obs: Observation, stamp: str) -> None:
        """把这一帧看到的地标全部记一遍。

        前置条件：**一步只调一次**——`stamp` 非空，调用方保证不会同一步调两次。
        """
        ...

    def note_step(
        self, before: Observation, action: Action, after: Observation
    ) -> list[ObjectFact]:
        """这一步碰到了什么语义记忆（object），记下来。返回被更新的条目（可能为空）。

        前置条件：`before`/`after` 都有 `place`。算不出确定的一格时（连按、
            原地转身、两个候选同时存在）**不记**，宁可漏记也不能记错格子。
        """
        ...
