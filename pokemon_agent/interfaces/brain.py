"""大脑接口 —— **所有需要 LLM 才能回答的问题，都在这个文件里**。

这条边界是按"错了会怎样"划的，和 `world/ram.py` 那条一样：

    需要判断、会错、要记账、要标定   ← BrainPort（模型）
    照抄内存、格式化、计数、查表     ← Tools / Harness（确定的）

## 大脑是被调用方，它不记账

三个方法都**不收 `episode_id`、不收 `step`、不碰 `TracePort`**，
而是把账（`ModelCall`）连同结果一起交出来，由 Harness 翻译成事件。

上一版不是这样：brain 自己写 MODEL_CALL / THINK / ERROR / MEMORY_READ，
harness 写 ACT / MEMORY_WRITE / OBSERVE / EPISODE_*，于是"某类事件归谁写"
要一条条记；而且为了让判定器碰不到自己的账，还给 `judge` 开了个不写 trace 的例外——
**用例外弥补一条不统一的规则**。

现在规则只有一句：**谁控制循环，谁记账。** 大脑连 `episode_id` 都拿不到，
它想影响自己在实验数据里的样子也没有入口。

## 三个方法，三条互不通气的链路

`choose` 和 `judge` **必须是两个模型、两份 prompt、两笔账**。
让做决策的那个模型顺带回答"我成功了吗"，就是**误差同源**：
它读错画面 → 以为达成了 → 判成功，而且错得越离谱数字越好看。
成功率是这个项目唯一要报的硬数字，它不能由被评价者自己给出。

所以 `judge` 拿不到决策者的**任何说辞**：拿不到 thought、拿不到候选动作、
拿不到历史里那几步的 `rationale`。**这条不许放宽。**

它**看得到**本局最近几步发生了什么（`history`）。那不是放宽，是补一个洞：
证据可能在三步前那一帧的对话框里，而一条第 10 步才压进来的子目标，
前 9 步根本没人问过它。**发生过的事**和**它对那件事的主张**是两样东西，
只给前者——渲染时一律 `MemoryEntry.render(reason=False)`。

目标栈接进来之后多了一条同样要紧的：**只有栈底那一层决定 episode 成败**。
子目标是 agent 自己压的，如果它完成也能写 `success`，那 agent 就可以压一个
"我已经到家了"的子目标让判定器判它完成——成功率变成它自己发的奖状。
所以子目标判成完成只弹栈，`success` 只在栈底那条被判成时才写。

## 实现方必须无状态

判据：连续两次用相同参数调用，行为必须一致。
episode 的状态全在 Harness 手里，通过参数传进来。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.core import (
    Action,
    ActionSpace,
    Decision,
    Goal,
    MemoryEntry,
    Observation,
    Verdict,
)


@runtime_checkable
class BrainPort(Protocol):
    """Harness 认识的大脑。**Harness 不认识任何具体模型。**"""

    def choose(
        self, goals: list[Goal], obs: Observation, space: ActionSpace
    ) -> Decision:
        """选出下一步动作，连同这次花了什么、翻过哪些记忆。

        `goals` 是**整个目标栈**，栈顶（最后一个）是这一轮要完成的那条。
        下面几层也要给：不给的话大脑不知道自己为什么在做这件事，
        也就无法判断这个子目标是不是已经偏离了任务。

        动作分三类（`Action.intent`），只有 `PRESS` 推进世界。
        允许哪几类由 `space.intents` 给出——**它由 Harness 填**，
        因为"还能不能再拆一层"取决于栈有多深。

        前置条件：`space.names` 与 `space.intents` 非空、`goals` 非空、
            `obs.done` 为 False。空动作空间是 Tools 的 bug，大脑不为它兜底。
        后置条件：`decision.action` 非 None 时，它的 `intent` 属于 `space.intents`，
            且 `PRESS` 时 `name` 属于 `space.names`；`decision.calls` 至少一条。

        **重试全部失败时返回 `action=None`，不抛异常。** 那是一类要被统计的
        失败模式，不是"再试试就好"；而"这一局要不要因此终止"是 Harness 的判断，
        大脑只如实汇报。

        模型调不通（网络、鉴权）仍然会抛——见 `judge` 那条的对照说明。
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
        """
        ...
