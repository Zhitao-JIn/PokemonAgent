"""工具层接口 —— 大脑伸向环境的手。

## 两个协议，因为有两个调用方

    ToolPort   大脑看到的。**这五个方法就是大脑能力的全集。**
    ToolHost   Harness 看到的。多出来的是"开局"和"这次观测是怎么来的"，
               都是大脑不该知道的事。

往 `ToolPort` 里加方法前先问一句：这是大脑该知道的事，还是循环控制的事？
放错一边的代价不对称——大脑多知道一件事，它就会开始围绕那件事推理。

## perceive 是纯读，**它不构成一步**

这一条踩过坑：`perceive()` 曾经既是"给大脑看一眼"，又是"新的一步开始了"。
两种身份对它的期待不一样，于是要靠"这一步我是不是已经记过 trace 了"去调和，
而那个判断本身就是 bug 的温床（实测出现过步号回退、判定重复计费）。

现在它只是查询：不写 trace、不推进世界、不触发判定。
**"一步"的边界由 Harness 定义**，那里只有两个地方会产出新的一步。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.core import (
    Action,
    ActionSpace,
    MemoryEntry,
    ObjectNote,
    Observation,
    Task,
    ToolResult,
)


@runtime_checkable
class ToolPort(Protocol):
    """大脑与外界的**唯一**通信边界（CLAUDE.md 铁律 2）。"""

    def perceive(self) -> Observation:
        """取当前观测。**幂等只读**：不推进世界、不写 trace、不触发判定。

        后置条件：同一帧内多次调用**不产生额外的模型调用**（实现方要在帧内缓存——
            感知是每步都要付钱的那一项）。

        返回内容在同一帧内也是稳定的，**除非期间调用过 `inspect()`**：
        那会往 facts 里加一条 `inspected`。这是刻意的（细看的答案要能被下一轮读到），
        但它意味着"幂等"只对模型调用成立，对返回值不成立。
        """
        ...

    def inspect(self, focus: str) -> Observation:
        """对同一帧再问一次感知，问一个具体的问题。**世界不推进。**

        前置条件：focus 非空。**没有具体问题就不该调它**——
            那样它只是把同一帧原样再看一遍（`perceive()` 帧内缓存，字节完全一样），
            不产生任何新信息，纯粹白烧一次调用。
        后置条件：答案并进下一次 `perceive()` 的 facts；`execute()` 之后自动失效。
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
        """
        ...

    def memory_query(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """检索相关记忆。

        前置条件：limit > 0。
        后置条件：返回条数 <= limit；按相关性降序。
            **检索策略属于实现方**——大脑不知道也不该知道记忆从哪来、怎么排的，
            机制一、机制三接进来时改的是实现，这个签名不动。
        """
        ...

    def recent(self, episode_id: str, limit: int) -> list[MemoryEntry]:
        """**这一局**最近几条，按时间顺序。

        前置条件：limit > 0。
        后置条件：返回条数 <= limit；全部来自 `episode_id` 这一局；最新的在最后。

        和 `memory_query` 是两件事，不能互相替代：那个按相似度找"以前的类似情形"，
        跨 episode，给的是**经验**；这个按时间取"刚刚发生了什么"，只限本局，
        给的是**证据**。判定器要的是后者，而且正因为它两头有界才是安全的。
        """
        ...

    def memory_write(self, entry: MemoryEntry) -> None:
        """写入一条记忆。

        前置条件：`entry.rationale` 非空。没有理由的经验取回来也没用——
            它说不出当时为什么这么判断，也就无法检查那个判断现在还成不成立。
        注意：Harness 也会写记忆。**大脑不能假设记忆库里只有自己写的东西。**
        """
        ...


@runtime_checkable
class ToolHost(ToolPort, Protocol):
    """Harness 看到的工具层：`ToolPort` 再加上开局与溯源。

    分成两个协议而不是一个，是为了让"大脑能力的全集"这句话**在类型上成立**。
    合成一个的话，`reset()` 就出现在大脑的工具清单里了——它会开始考虑要不要重开一局。
    """

    def reset(self, task: Task) -> Observation:
        """按任务重置到初始状态并返回首个观测。

        前置条件：`task.max_steps > 0`。
        后置条件：`done` 为 False；`step` 未盖章（由 Harness 填 0）。
        """
        ...

    def drain_calls(self) -> list[dict[str, str]]:
        """取走**自上次取走以来**发生的每一次模型调用，并清空。

        后置条件：连着调两次，第二次返回空列表。不调用模型的实现恒返回空列表，
            **不返回 None**。

        ## 为什么是"取走"而不是"最近一次"

        早一版是 `last_calls` 属性，由**生产方**在下一次感知时清空。
        那样它的正确性取决于"记账的人来得够早"，而这个前提两边都会破：

        - 清得太晚（缓存命中时不清）：不推进世界的那些轮次（细看、拆子目标）
          会把上一轮的账**再记一遍**，而且 inspect 的账会被当成 perceive 的账，
          prompt 归因跟着错乱。
        - 清得太早（进门就清）：`reset()` 里那次真实调用的账，会被紧接着那次
          命中缓存的 `perceive()` 冲掉，**钱花了但没有记录**。

        两个方向都错，说明问题不在时机而在归属。改成取走之后，不变量变成
        **每一次调用恰好被记一次账**——它由调用次数本身保证，不依赖调用顺序。
        """
        ...

    def note_seen(self, obs: Observation, stamp: str) -> None:
        """把这一帧看到的地标全部记进档案，**没互动过的也记**。

        前置条件：**一步只调一次**（`seen` 是"进过几次视野"）。
        后置条件：档案里出现这一帧的每一个地标；已有的更新 `last_seen`。

        没互动过的也建档，是因为档案最有价值的一类条目正是
        "这里有一扇门，我见过 7 次，一次都没进去过"——**那是它自己的待办清单**。

        `stamp` 是调用方给的不透明时刻标记；实现方不解释它，也就不需要知道 episode 是谁。
        """
        ...

    def note_step(
        self, before: Observation, action: Action, after: Observation
    ) -> list[ObjectNote]:
        """这一步碰到了什么，记进档案。返回被更新的条目。

        两件事：**互动**（按 `a` → 面朝那格给了什么文字）和
        **穿门**（按方向键且地图变了 → 那扇门通往哪张地图）。

        后置条件：**面朝哪一格必须是算出来的**（位置 + 朝向，两个确定量），
            不能靠模型认"我刚才在跟谁说话"——键错了这套档案就没有意义。
            连按穿门（`times > 1`）时**宁可漏记**：门可能在中途任意一格，
            把 `leads_to` 挂到错的门上，那条错会被当成事实反复使用。

        **没有文字也要记**："我试过，没反应"本身就是有用的，它下次就不会再按一遍。
        """
        ...

    @property
    def last_frame_sha(self) -> str:
        """最近一次观测所依据的那一帧的哈希。

        没有它，一条读错的观测**无法追查是哪一帧**——而那是查感知错误的起点。
        没有"帧"这个概念的实现返回空串。
        """
        ...
