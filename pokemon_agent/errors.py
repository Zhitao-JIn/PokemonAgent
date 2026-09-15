"""预期内的失败——**跨模块的共同祖先与升级态**。

划分依据（CLAUDE.md 第八节）：**调用方违约用 assert，外部世界不配合用这里的异常。**
每类失败有名字，是因为 replay 要按失败类型归类统计——
"修了 Z 类失败模式"这句话的 Z 就是这里的类数。

**0913 拆分：模块自己的词汇回自己家，这里只留跨模块的。** 判据是
**"拷走这个模块，还欠外面什么"**——它自带的词汇必须跟着走，除非那条异常
**真的会走到本文件的捕获点**（那样它才需要本文件的根）。

| 留在这里的 | 为什么不能进模块 |
|---|---|
| `AgentError` | 全体根。`episode_error_handler` 只捕它——"单局异常不崩掉整个 run"
  这条 run 级策略需要一个所有**跨模块**异常都继承的共同祖先（tool 层的
  `MaxRetriesExceeded`） |
| `MaxRetriesExceeded` | **tool 抛、harness 接**：它描述的是"重试预算耗尽"这个
  **调用方处境**，不是任何模块自己的词汇。模块只管"这一次成没成"（brain 抛
  `AttemptFailed`、world 抛 `PerceptionAttemptFailed`），"这条链路彻底完了"
  由循环控制者（`BrainTool` / `GameTools`）宣布 |

**搬走的**（各自回了模块内部，且**都不继承 `AgentError`**——0913 深夜十一修正
brain，0913 夜修正 world）：

- **brain 的词汇** → `pokemon_agent/brain/errors.py`：
  `ParseFailure` / `IllegalAction` / `OutputTruncated` / `ToolTimeout` /
  `ProviderRejected` / `AttemptFailed` 家族（`Decision` / `Plan` / `Judge` /
  `Verify` / `Summarize` / `Extract`）。
  brain 要能被整体拷走，词汇得跟着走；**且它有一根自己的根 `BrainError`**——
  此前继承这里的 `AgentError`，但实测那些异常全被 `BrainTool._attempt_loop`
  接住、翻译成 `MaxRetriesExceeded` 才上抛，**走不到 harness 的捕获点**，
  "共同祖先"是纯仪式。留一个外部基类等于 brain 拷走后还得带上本文件才能跑。
- **world 的词汇** → `pokemon_agent/world/errors.py`：
  `PerceptionAttemptFailed`——它现在也**自成一根 `WorldError`**（0913 夜）。
  改动的原因是 **P4**：world 的重试循环原本建在 harness 节点
  （`press/perceive_after_action.py` 里那个 `for attempt in ...`），
  于是 world 的异常真的跨上了 harness；0913 夜把它搬回 tool 层
  （`GameTools.perceive_with_retry`，与 `BrainTool._attempt_loop` 同形），
  world 的词汇**在桥上就被翻译掉**——继承随之失去对象。
  **world 与 brain 现在同一规格。**

**"继承 `AgentError`"的判据（0913 深夜十一确立，0913 夜在 world 上第二次适用）**：
**只有真的会走到 harness 捕获点的模块异常才需要继承它。**
判据问的不是"谁抛谁接"，是**"这条异常有没有跨过 tool 层这座桥"**：
brain 的异常在 `BrainTool._attempt_loop` 被吃掉、翻译成 `MaxRetriesExceeded`，
world 的异常在 `GameTools.perceive_with_retry` 被同样处理——**两者都在 tool 层
止步**，所以两者都自成一根。跨过桥的只有 `MaxRetriesExceeded` 本身，
它本来就是本文件的住户。

**所以"子类搬走、根留下"现在没有对象了**：四个独立模块（brain / world /
memory / trace）里，**没有任何模块异常真的走到 harness 的捕获点**——桥建在
tool 层，模块的词汇在桥上翻译。`episode_error_handler` 捕的是**tool 层宣布的
升级态**，不是模块的原始词汇。

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
    # 只在类型层面需要：`MaxRetriesExceeded.calls` 是**跨层信封那份**
    # `ModelCall`（实体住 `schemas/harness/communication/ModelCall.py`，
    # 由 `schemas/harness/__init__.py` 出口）——brain 交出来的方言账已由
    # `BrainTool._adopt()` 翻译成这一份，是 tool 层的工作形状。
    # 运行时完全不碰它（`list(calls)` 只迭代实参），且 `from __future__ import
    # annotations` 让签名注解都是字符串，所以放 TYPE_CHECKING 即可。
    from pokemon_agent.schemas.harness import ModelCall


class AgentError(Exception):
    """本项目所有预期内失败的基类。捕获它意味着"我知道这里会出问题"。

    **它不是"所有模块异常的共同祖先"**（docstring 曾这么写，0915 更正）——
    brain/world 的异常 0913 起各自成根（`BrainError`/`WorldError`），在 tool 层
    的桥上就被翻译掉，走不到 harness 的捕获点；真正继承它的只有本文件的
    `MaxRetriesExceeded`。见本文件模块 docstring 的"跨桥判据"。
    """


class MaxRetriesExceeded(AgentError):
    """连续重试仍拿不到可用结果。

    到这一步说明模型在当前状态下持续失败，是一条要进 trace 并被 replay 统计的失败模式，
    不是"再试试就好"。

    **谁抛**：tool 层的两个循环控制者——`BrainTool._attempt_loop`（六条链路统一重试
    `BRAIN_MAX_ATTEMPTS` 次）与 `GameTools.perceive_with_retry`（感知链重试
    `PERCEPTION_MAX_RETRIES` 次）。
    **谁接**：harness 的调用点——它决定这一局/这一轮怎么收场（`choose` 耗尽让这一局
    失败，`plan` 耗尽路由 review 交人工，感知耗尽让这一局以错误收场，等）。
    **`extract` 那个调用点把 `except` 写成了"落账 + 继续"**（0914 S4）：知识抽取是
    附加产物，拿不到它不该让这一局从成功率的分母上掉出去——见
    `harness/episode/close/extract_knowledge.py`。

    **它为什么不进 brain**（0913）：brain 只回答"这一次成没成"（抛 `AttemptFailed`），
    不含"重试几次""耗尽之后怎么办"这些**调用方处境**的知识。循环在 tool 层，所以这个
    "预算耗尽"的升级态也归 tool 层宣布。它留在顶层是因为**抛的人（tool）与接的人
    （harness）分属两层**，它不属于任何单一一层。

    `calls`：**整条失败账**（每一次尝试的 `ModelCall`，按发生顺序），可空——
    循环在 `BrainTool` 里，它把账打包随异常带出来，宿主节点一步落账，
    不用再回头找中间状态。**类型是跨层信封那份 `ModelCall`**
    （`schemas/harness/communication/ModelCall.py`）——brain 交出来的方言账
    由 `BrainTool._adopt()` 翻成这一份。**账上没有"第几次尝试"字段**：
    每条账各代表一次尝试，所以尝试次数就是 `len(calls)`。

    `source`：哪条链路耗尽（`"decide"` / `"plan"` / `"judge"` / `"verify"` /
    `"summarize"` / `"extract"` / `"perception"`）。同一个异常类被七条链路共用，
    `source` 是调用方分辨"是谁完了"的依据——没有它就只能靠调用点位置倒推，
    而重试循环在 tool 层，调用点与链路已不是一一对应。
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
