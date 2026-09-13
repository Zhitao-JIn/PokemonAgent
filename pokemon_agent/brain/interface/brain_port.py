"""brain **模块层**的对外契约：`BrainPort`。

**这是第三方模块的视角**，不是本项目 harness 的视角。读这个文件的人应该能
只靠它就知道"大脑能做什么、要给它什么、它给你什么"——**不需要知道本项目
有 harness、有 trace、有 memory**。

三条边界：

1. **入参是裸字段 + 少数关键数据结构。** 没有 `*Req` 信封——信封是"某一跳"
   的概念（harness→tool 那一跳有自己的信封），不属于模块层。大部分素材是
   `str`（历史、目标、prompt 都是渲染好的文本）；**只有参与逻辑运算或
   索引对齐的"关键字段"才要数据结构**：`keys`（要拿它校验动作合法性）、
   `images`（多模态素材，物理上塞不进文本）、`entries`（`verdicts` 的
   `index` 要落回它的下标）。
2. **prompt 是规则，入参是素材。** "怎么判、怎么想、怎么规划"全在 prompt 里
   （调用方组装、brain 原样拿去问模型的）；"判什么、想什么"才是入参。
   所以同一个东西不会既在 prompt 里又在入参里传两遍——**论据就是这样去掉的**。
3. **返回值是 brain 自己的方言**，谁要用谁转换（`tools/brain_tool.py`）。
   `brain` 的 `__init__` 只收 provider，不读任何本项目配置——**当作能被整体
   拷走复用**，跟 `memory/` 同一个规格。

方法名与"一个方法一件事"对应：`choose`/`reflect`/`judge`/`plan`/`verify`/
`summarize`。**没有 `*_once` 后缀**——"一次"是调用方的循环术语，模块层的方法
天然就是"做一次"。

**六个方法的形状统一**：`prompt`（规则）+ 素材 + 可选 `images`。每个方法都
接受 `images`——多模态素材物理上塞不进文本 prompt，只能独立传；默认空序列
表示这次纯文本（`judge`/`verify`/`summarize` 会据此从 `describe()` 降级到
`complete()`）。

**六个方法的失败语义也统一：一律抛 `AttemptFailed` 家族，一律不重试。**
这是本契约里最容易被写歪的一条，所以写在这里：

| 方法 | 失败时抛 | 携带 |
|---|---|---|
| `choose` | `DecisionAttemptFailed` | 这一次尝试的 `ModelCall` |
| `plan` | `PlanAttemptFailed` | 同上 |
| `judge` | `JudgeAttemptFailed` | 同上 |
| `verify` | `VerifyAttemptFailed` | 同上 |
| `summarize` | `SummarizeAttemptFailed` | 同上 |
| `reflect` | 不调模型，只在调用方违约时 assert | — |

**为什么失败必须抛、不许降级**：判定/校验/蒸馏曾经把失败吞成"一个看起来
正常的业务结果"（`done=False` / 全标不可靠 / `summary=None`），后果是
**"这条链路坏了"和"业务结论就是如此"在数据里完全分不开**——trace 里只看到
成功率悄悄变 0，而失败原因不在任何一条事件里。抛出来之后，调用方的重试预算
接手：先重试，仍失败就是一条可见的错误事件。

**为什么不在模块内部重试**：重试是循环控制，而"失败之后该怎么办"依赖调用方
的处境（决策失败让这一局失败、规划失败交人工、校验失败可以降级继续）。
模块层只回答"这一次成没成"，不问"下一步怎么办"。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .domain import (
    ChooseResult,
    JudgeResult,
    PlanResult,
    Reflection,
    SummarizeResult,
    VerifyResult,
)


@runtime_checkable
class BrainPort(Protocol):
    """大脑模块的对外能力。"""

    # ---- 决策 ----

    def choose(
        self,
        *,
        prompt: str,
        keys: Sequence[str],
        images: Sequence[bytes] = (),
    ) -> ChooseResult:
        """选一个动作，连同理由。

        prompt：完整 prompt——动作空间说明、目标栈、已知事实、记忆、
            领域知识、人类插话，以及"怎么选"的全部规则，都由调用方渲染好。
            `BrainPort` 不提供任何"帮你拼 prompt"的方法，`Brain` 只认
            `prompt`。
        keys：此刻可用的按键名。**唯一的用途是校验动作合法性**——说明文字
            不在这里（它们只进 prompt，且不参与逻辑运算）。
        images：可选的多模态素材。空序列 = 这次纯文本。

        前置条件：`keys` 非空（空动作空间是调用方的 bug——那种情况该在
            调用方就被判成"这一步没法走"，不该问模型）。
        后置条件：`result.action.sequence` 里每个 `name` 都在 `keys` 内；
            `result.calls` 恰好一条（这次尝试自己的账，多次尝试的累积归调用方，
            不在这里滚存）。
        失败：抛 `DecisionAttemptFailed`（附这次的账）——模型调不通、解析不出、
            选了不存在的键、被截断，全走这一个出口。
        """
        ...

    # ---- 反思 ----

    def reflect(
        self,
        *,
        prompt: str,
        before: str,
        after: str,
        action_text: str,
        rationale: Sequence[str],
    ) -> Reflection:
        """把这一步整理成一条经验：**看到什么 → 为什么 → 做了什么 → 变成什么**。

        prompt：这次整理的规则。**本版不消费它**（四样素材已经在参数里，
            让模型再复述一遍只会引入它自己的措辞偏差，还多烧一次调用）——
            这个参数在这儿是因为 `reflect` 后面也要接 LLM（接口按"可能会调"
            设计），六个方法形状统一。
        before/after：前后两帧观测的**渲染文本**（渲染是调用方的事——剪哪些
            字段、怎么对齐，都是渲染策略，随世界和存储策略变）。
        action_text：这一步做了什么。
        rationale：这段动作的论据。

        前置条件：`before`/`after` 非空、`rationale` 非空——调用方要保证
            （渲染是它的事，给空串是它的 bug，本方法 assert 拦下）。
        后置条件：返回的 `Reflection` 四个字段与入参一一对应。
        **本方法不写库**（写库是状态变更，而大脑无状态），**不盖章坐标**
            （`episode_id`/`step` 由调用方加）。
        """
        ...

    # ---- 判定 ----

    def judge(
        self,
        *,
        prompt: str,
        goal: str,
        history: Sequence[str],
        images: Sequence[bytes] = (),
    ) -> JudgeResult:
        """判断这个目标达成了没有。

        **判定必须的三块：`goal` / `history` / `prompt`。** 它们各自回答一个
        独立的问题，缺一块判定就不成立：

        - `goal`：判**哪个**目标。
        - `history`：拿**什么**判——本局最近几步的事实（渲染好的文本，不含
          决策者的说辞）。
        - `prompt`：**怎么**判——判定规则、输出格式、四类判据的核对方式。

        `history` 是**已渲染好的文本序列**（每条一个字符串），不是
        `StepMemory`——渲染是调用方的事（剪哪些字段、怎么去重，都是渲染策略）。

        **和 `prompt` 不重复**：`prompt` 是规则模板，`goal`/`history` 是素材。
        调用方可以把它们也渲进 `prompt`（本项目的 `judge_success.build_prompt()`
        就渲了），但**签名里必须留位**——这里表达的是"判定这件事必须有这几块"
        这个**约定**，不是"调用方一定另给一份"。谁要整体拷走 brain 复用时，
        只看这个签名就知道喂什么。

        images：可选截图，这次判定要看的画面。

        后置条件：`result.calls` 恰好一条；`result.done` 是模型明确给出的布尔裁决
            （本方法不替模型猜）。
        失败：抛 `JudgeAttemptFailed`（附这次的账）——**"永远返回一个判定"这条
            旧契约已废弃**。旧写法把调用失败吞成 `done=False`，于是"判定器坏了"
            与"真的没达成"在数据里分不开；现在失败必须被看见。
            注意：`prompt` 的拼装（可能抛 `KeyError`）发生在调用方，
            调用方要自己兜住，不能指望 `judge()` 替它兜。
        """
        ...

    # ---- 规划 ----

    def plan(
        self,
        *,
        prompt: str,
        goal_stack: Sequence[str],
        history: Sequence[str],
        max_push: int,
        images: Sequence[bytes] = (),
    ) -> PlanResult:
        """run 级规划：根据历史决定目标栈怎么变。

        **规划必须的四块：`goal_stack` / `history` / `max_push` / `prompt`。**

        - `goal_stack`：当前目标栈（**栈顶在最后**，调用方按 LIFO 原序给）。
        - `history`：run 级的"发生过什么"——**已渲染好的文本序列**，
          本项目按"每局一行"折（`- ep1: 目标 → 成功（12 步，reason）`）。
          不是 `TraceEvent`——事件流是 harness 的存储形状，渲染成文本是调用方的事。
        - `max_push`：这一次最多允许压几个子目标（**硬约束，不是素材**——
          模型可能压超，harness 侧要按它裁）。
        - `prompt`：怎么规划、输出什么格式的规则。

        images：可选截图。本版 `plan_llm` 是纯 `LLMProvider`，收下但不用。

        **与 `prompt` 不重复**：本项目把这四块都渲进了 `run_plan.md` 的对应占位符，
        但签名立的是"规划必须有这几块"这个约定——谁整体拷走 brain 复用时，
        只看签名就知道喂什么。

        后置条件：`result.calls` 恰好一条。
        失败：抛 `PlanAttemptFailed`（附这次的账）。
        """
        ...

    # ---- 校验 ----

    def verify(
        self,
        *,
        prompt: str,
        entries: Sequence[str],
        goal: str,
        knowledge: str,
        include_rationale: bool,
        images: Sequence[bytes] = (),
    ) -> VerifyResult:
        """逐条判定这一局的 step 记录哪些可信。

        **校验必须的五块：`entries` / `goal` / `knowledge` /
        `include_rationale` / `prompt`。**

        - `entries`：**要逐条判定的素材**——`result.verdicts` 里每条判定的
          `index` 就指向它的下标，所以这里必须给条目本身、不能只给条数：
          调用方要能知道"是哪一条错了"。
        - `goal`：这些记录是为哪个目标做的——校验要看"这一步对目标有没有用"，
          脱开目标就只剩格式检查。
        - `knowledge`：领域知识（本项目是可检索的经验条目），空串表示没有。
        - `include_rationale`：**`entries` 里要不要包含决策者的论据**。
          **这是一块显式约定，不藏在调用方的渲染里**：本项目 `verify()` 传
          `False`——校验看"发生了什么"，**不该看到决策者自己的说法**
          （那正是要被校验的对象，先看到就自带偏向）；`summarize()` 传 `True`。
          把它摆在签名上，是因为"要不要给论据"是**校验这件事的语义选择**，
          不是某个渲染函数的实现细节。
        - `prompt`：怎么判、输出什么格式的规则。

        images：可选截图。

        后置条件：`verdicts` 与 `entries` **等长**且按 `index` 顺序；
            `calls` 恰好一条。
        失败：抛 `VerifyAttemptFailed`（附这次的账）——**"永远返回一份裁决"
            这条旧契约已废弃**。**过滤仍不在这里**——本方法只判，
            谁想用可信的那部分自己筛。
        """
        ...

    # ---- 蒸馏 ----

    def summarize(
        self,
        *,
        prompt: str,
        goal: str,
        history: Sequence[str],
        success: bool,
        steps: int,
        max_steps: int,
        images: Sequence[bytes] = (),
    ) -> SummarizeResult:
        """把这一局蒸馏成一条跨局经验。

        **蒸馏必须的六块：`goal` / `history` / `success` / `steps` / `max_steps`
        / `prompt`。**

        - `goal`：这一局打的是什么目标。
        - `history`：这一局可信步骤的记录（**已渲染好的文本序列，含决策者
          的论据**——蒸馏要总结"为什么这么做"，说辞在这里是有用素材）。
          调用方拿 `verify()` 的 `verdicts` 自己筛完再传（**过滤是调用方的事**，
          这样想怎么用就怎么用）。
        - `success` / `steps` / `max_steps`：这一局的**结局与预算**——
          蒸馏要评价"这个做法值不值得复用"，不知道它是成功还是失败、
          花了多少步，评价就没有基准。
        - `prompt`：怎么蒸馏、输出什么格式的规则。

        images：可选截图。

        前置条件：`history` 只装**已过滤的可信记录**，且至少一条——
            本方法不校验素材的可信度（那归调用方），也不认识"条目"。
        后置条件：`result.summary` 非 `None`；`calls` 恰好一条。
        失败：抛 `SummarizeAttemptFailed`（附这次的账）——"这次没蒸出东西"
            不是一种正常返回，而是一次失败。
        """
        ...
