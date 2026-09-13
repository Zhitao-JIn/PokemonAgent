"""预期内的失败——**跨模块的共同祖先与升级态**。

划分依据（CLAUDE.md 第八节）：**调用方违约用 assert，外部世界不配合用这里的异常。**
每类失败有名字，是因为 replay 要按失败类型归类统计——
"修了 Z 类失败模式"这句话的 Z 就是这里的类数。

**0913 拆分：模块自己的词汇回自己家，这里只留跨模块的。** 判据是
**"拷走这个模块，还欠外面什么"**——它自带的词汇必须跟着走，除非那条异常
**真的会走到本文件的捕获点**（那样它才需要本文件的根）。

| 留在这里的 | 为什么不能进模块 |
|---|---|
| `AgentError` | 全体根。`RunHarness.dispatch` 只捕它——"单局异常不崩掉整个 run"这条
  run 级策略需要一个所有**跨模块**异常都继承的共同祖先（tool 层的
  `MaxRetriesExceeded`、world 的感知失败）。**只有真的要跨过 tool 层、走到这个
  捕获点的模块异常才继承它** |
| `MaxRetriesExceeded` | **tool 抛、harness 接**：它描述的是"重试预算耗尽"这个
  **调用方处境**，不是 brain 的词汇。brain 只管"这一次成没成"（抛 `AttemptFailed`），
  "这一步彻底完了"由循环控制者（`BrainTool`）宣布 |

**搬走的**（各自回了模块内部，且**不再继承 `AgentError`**——0913 深夜十一修正）：

- **brain 的词汇** → `pokemon_agent/brain/errors.py`：
  `ParseFailure` / `IllegalAction` / `OutputTruncated` / `ToolTimeout` /
  `AttemptFailed` 家族（`Decision` / `Plan` / `Judge` / `Verify` / `Summarize`）。
  brain 要能被整体拷走，词汇得跟着走；**且它有一根自己的根 `BrainError`**——
  此前继承这里的 `AgentError`，但实测那些异常全被 `BrainTool._attempt_loop`
  接住、翻译成 `MaxRetriesExceeded` 才上抛，**走不到 harness 的捕获点**，
  "共同祖先"是纯仪式。留一个外部基类等于 brain 拷走后还得带上本文件才能跑。
- **world 的词汇** → `pokemon_agent/world/errors.py`：
  `PerceptionAttemptFailed` / `PerceptionFailure`——它们是**唯一真正上抛到
  harness 的模块异常**（`perceive_after_action.py` 直接 `except
  PerceptionAttemptFailed`），所以**保留 `AgentError` 继承**。

**"继承 `AgentError`"的判据（0913 深夜十一确立）**：**只有真的会走到 harness
捕获点的模块异常才需要继承它。** brain 的异常在 tool 层就被吃掉、翻译了，
所以不继承；world 的异常被 harness 节点直接捕获，所以要继承。
继承与否反映的是"这条异常有没有跨过 tool 层这座桥"。

**为什么子类搬走、根留下**：两边各取所需——**会跨过 tool 层的**模块异常自带
词汇且继承本根（world 的），**在 tool 层就被吃掉的**自带词汇但不继承
（brain 的）；harness 只有一个捕获点（`except AgentError` 一网打尽）。

**`ImageNotDelivered` 回 brain 了**（0913 深夜十一）：它由 `brain/providers.py::describe()`
抛出，所以**归 brain**（`brain/errors.py`）。world 侧的 `describe()` 由 world 自己的
`VisionProvider` 协议声明、brain 侧由 brain 自己的 `JudgeProvider` 声明；实现
（`brain/providers.py` 的 `_MultimodalMixin`）**同时满足两个协议**，抛的是 brain 的
`ImageNotDelivered`。**world 不再认识它**——world 的感知链在 `PyBoyWorld.perceive_once`
里就地 `except Exception` 包成自己的 `PerceptionAttemptFailed`，把"这次没读出来"这个
world 才知道的处境讲出来。这样 brain 拷走后不欠外面任何东西。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 只在类型层面需要：`MaxRetriesExceeded.calls` 是 **tool 层**那份
    # `ModelCall`（`tools.interface.ModelCall`，实体在 `schemas/harness`）——
    # 账从 brain 交出来时已被 `BrainTool` 的循环"收编"，是 tool 层的工作形状。
    # 运行时完全不碰它（`list(calls)` 只迭代实参），且 `from __future__ import
    # annotations` 让签名注解都是字符串，所以放 TYPE_CHECKING 即可。
    from pokemon_agent.tools.interface import ModelCall


class AgentError(Exception):
    """本项目所有预期内失败的基类。捕获它意味着"我知道这里会出问题"。

    **它是所有模块异常的共同祖先**（brain/world 的异常都继承它），所以必须住在这个
    谁都能 import 的顶层。`RunHarness.dispatch` 只捕它——"单局异常不崩掉整个 run"
    这条契约就落在这个捕获点上。
    """


class MaxRetriesExceeded(AgentError):
    """连续重试仍拿不到可用结果。

    到这一步说明模型在当前状态下持续失败，是一条要进 trace 并被 replay 统计的失败模式，
    不是"再试试就好"。

    **谁抛**：`BrainTool`（五条链路统一重试 `BRAIN_MAX_ATTEMPTS` 次的那个循环）。
    **谁接**：harness 的调用点——它决定这一局/这一轮怎么收场（`choose` 耗尽让这一局
    失败，`plan` 耗尽路由 review 交人工，等）。

    **它为什么不进 brain**（0913）：brain 只回答"这一次成没成"（抛 `AttemptFailed`），
    不含"重试几次""耗尽之后怎么办"这些**调用方处境**的知识。循环在 tool 层，所以这个
    "预算耗尽"的升级态也归 tool 层宣布。它留在顶层是因为**抛的人（tool）与接的人
    （harness）分属两层**，它不属于任何单一一层。

    `calls`：**整条失败账**（每一次尝试的 `ModelCall`，按发生顺序），可空——
    循环在 `BrainTool` 里，它把账打包随异常带出来，宿主节点一步落账，
    不用再回头找中间状态。**类型是 tool 层那份 `ModelCall`**
    （`tools.interface.ModelCall`）——账从 brain 交出来时已被循环"收编"，
    盖过 `attempt`，是 tool 层的工作形状。

    `source`：哪条链路耗尽（`"decide"` / `"plan"` / `"judge"` / `"verify"` /
    `"summarize"`）。同一个异常类被五条链路共用，`source` 是调用方分辨
    "是谁完了"的依据——没有它就只能靠调用点位置倒推，而重试循环在 tool 层，
    调用点与链路已不是一一对应。
    """

    def __init__(
        self,
        attempts: int,
        last_reason: str,
        calls: Sequence[ModelCall] = (),
        source: str = "",
    ) -> None:
        """记下试了几次、最后一次为什么失败、整条账、以及哪条链路。"""
        label = source or "unknown"
        super().__init__(f"[{label}] gave up after {attempts} attempts, last: {last_reason}")
        self.attempts = attempts
        self.last_reason = last_reason
        self.calls: list[ModelCall] = list(calls)
        self.source = source


__all__ = ["AgentError", "MaxRetriesExceeded"]
