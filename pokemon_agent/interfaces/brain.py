"""Harness 认识的大脑：三个方法，`choose` / `judge` / `reflect`。

**Harness 不认识任何具体模型。** 换 provider、换 prompt、乃至把 `reflect` 从
"纯拼装"改成"调一次模型"，循环这一侧一行不用改。

三条贯穿全文件的契约：

- **大脑不持有任何工具/记忆实例。** 它该看到什么完全由参数表决定——`choose()` 的
  `memories` 和 `judge()` 的 `history` 都是 Harness 检索好递进来的，不给它一个
  能自己去翻记忆库的通道。检索策略是循环控制的事。
- **大脑不知道自己在哪一局。** 没有 `episode_id` / `step` 参数，`reflect()` 返回的
  条目也把 `episode_id` 留空由 Harness 盖章。
- **"调不通"和"调通了但没用"必须分得开。** 前者抛异常（网络、鉴权），后者走返回值
  （`choose` 返回 `action=None`、`judge` 返回 `done=False` 加一条失败记录）。
  混在一起，replay 就分不出"模型坏了"和"模型答错了"。

为什么 `choose` 和 `judge` 必须是两条独立链路（误差同源、各自标定），
见 `docs/spec/brain/SPEC.md`。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.action import Action, ActionSpace, Goal
from pokemon_agent.schemas.memory_episodic import MemoryEntry
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.schemas.trace import Decision, Verdict


@runtime_checkable
class BrainPort(Protocol):
    """Harness 认识的大脑。**Harness 不认识任何具体模型。**

    **大脑不持有任何工具/记忆实例。** `choose()` 需要的情景记忆由 Harness 检索好，
    当参数 `memories` 传进来——这条和 `judge()` 的 `history` 是同一个道理：
    大脑该看到什么，完全由方法的参数表决定，不给它一个能自己去翻记忆库的通道。
    早一版是大脑自己持有 `tools` 去调 `memory_query`——"大脑自己决定检索什么"
    听起来是给它自由度，实际效果是**记忆检索这件"循环控制的事"混进了大脑的构造函数**，
    而且这条通道再也没被用来做别的事。收回来之后 `Brain` 连一个 Protocol 类型的
    协作者都不用持有，无状态这条铁律在类型层面更容易守住。
    """

    def choose(
        self, goals: list[Goal], obs: Observation, space: ActionSpace,
        memories: list[MemoryEntry],
    ) -> Decision:
        """选出下一步动作，连同这次花了什么。

        `goals` 是**整个目标栈**，栈顶（最后一个）是这一轮要完成的那条。
        下面几层也要给：不给的话大脑不知道自己为什么在做这件事，
        也就无法判断这个子目标是不是已经偏离了任务。

        `memories` 是 Harness **检索好**的情景记忆，直接进 prompt。
        检索策略（按什么查、查几条）不是大脑的事——大脑只回答"给了我这些，
        我选哪个动作"，这也是为什么 `Decision.recalled` 直接从这个参数派生，
        不需要大脑自己去记"我刚才翻了哪几条"。

        **这一版只有按键一类动作。** `Action.intent` 那套分派（press / push_goal）
        连同枚举一起删了，拆子目标的机制会在别处重写。所以 `space` 里只剩 `names`，
        大脑只回答"按哪个键"。

        前置条件：`space.names` 非空、`goals` 非空、`obs.done` 为 False。
            空动作空间是 Tools 的 bug，大脑不为它兜底。
        后置条件：`decision.action` 非 None 时，它的 `name` 属于 `space.names`；
            `decision.calls` 至少一条。

        **重试全部失败时返回 `action=None`，不抛异常。** 那是一类要被统计的
        失败模式，不是"再试试就好"；而"这一局要不要因此终止"是 Harness 的判断，
        大脑只如实汇报。

        模型调不通（网络、鉴权）仍然会抛——见 `judge` 那条的对照说明。

        把当前处境交给决策模型，换回一个合法动作和这次的账。
        """
        ...

    def judge(
        self, goal: Goal, obs: Observation, history: Sequence[MemoryEntry] = ()
    ) -> Verdict:
        """判断**这一个目标**达成了没有。**永远返回 Verdict，不抛异常。**

        任务目标和子目标走同一个方法，只是 `goal` 从栈的不同层取——
        判定在两种粒度上是同一回事：拿着一句判据去看一帧画面。
        分成两个方法只会得到两份要各自标定的 prompt。
        区分哪一层是调用方的事（Harness 在 trace 里标 `depth`）。

        `history` 是**本局最近几步**，按时间顺序，**不含 `rationale`**。
        默认空元组：不传也要能判——多一份历史是多一份证据，不是必需品。

        前置条件：无。哪怕 obs 是空的也要能回答（答案是"没完成"）。
        后置条件：任何异常情况——解析失败、模型不回话、网络抖——一律判**没完成**。

        理由不对称：判成"完成"会立刻终止这一局，后面所有步骤都不会发生，
        而且这个结论直接进实验数据；判成"没完成"只是多跑几步，下一步还有机会纠正。
        所以所有不确定都往"没完成"倒。

        **和 `choose` 的差别是有意的**：判定器坏掉不该让一局崩掉——那会把一次
        可以标记为"判定失败"的事件，变成一局丢失的数据；而决策模型真的调不通时，
        这一局本来就跑不下去，硬撑只会产出一串没有意义的步骤。

        拿目标、判据和这一帧问一次判定模型，返回达成与否及依据。
        """
        ...

    def reflect(
        self, before: Observation, action: Action, after: Observation
    ) -> MemoryEntry:
        """把这一步整理成一条可检索的经验：**看到什么 → 为什么 → 做了什么 → 变成什么**。

        前置条件：`action.rationale` 非空。
        后置条件：返回的 entry 内容完整；`episode_id` 留空由 Harness 盖章
            （和 `Observation.step` 一个道理——大脑不知道自己在哪一局）。

        **这个方法自己不写库。** 写库是状态变更，而大脑无状态。让它返回、
        由 Harness 落库，"谁改了记忆"就永远只有一个答案。

        把前后两帧和这次动作拼成一条可检索的记忆条目返回。
        """
        ...
