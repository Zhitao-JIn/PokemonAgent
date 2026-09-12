"""预期内的失败。

划分依据（CLAUDE.md 第八节）：**调用方违约用 assert，外部世界不配合用这里的异常。**
每类失败有名字，是因为 replay 要按失败类型归类统计——
"修了 Z 类失败模式"这句话的 Z 就是这里的类数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokemon_agent.providers import ModelCall


class AgentError(Exception):
    """本项目所有预期内失败的基类。捕获它意味着"我知道这里会出问题"。"""


class ParseFailure(AgentError):
    """LLM 输出无法解析成 Action。

    这是**最常见**的一类，且是可重试的。带上原始文本，因为 replay 时要看模型到底吐了什么。
    """

    def __init__(self, raw_text: str, reason: str) -> None:
        """记下模型吐了什么、为什么解析不了。"""
        super().__init__(f"{reason}: {raw_text!r}")
        self.raw_text = raw_text
        self.reason = reason


class IllegalAction(AgentError):
    """LLM 选了一个不在 action space 里的动作。

    注意这和 `execute()` 入口的 assert 不冲突：
    - 这里是**大脑内部**发现模型幻觉，属于外部输入不合法 → 异常 + 重试。
    - assert 在 `execute()` 入口，防的是大脑**没做这个检查就把动作递出去** → 调用方 bug。
    两道防线针对两个不同的责任方。
    """

    def __init__(self, name: str, allowed: list[str]) -> None:
        """记下它选了哪个动作、当时允许哪些。"""
        super().__init__(f"action {name!r} not in action space {allowed}")
        self.name = name
        self.allowed = allowed


class OutputTruncated(AgentError):
    """模型话没说完就被 max_tokens 切断了。

    **必须和 `ParseFailure` 分开。** 截断在下游长得和"模型不会写 JSON"一模一样
    （都是少个右括号），但修法完全相反：截断要调大额度或让模型少说，
    格式错要改 prompt 或上约束解码。混成一类，统计里就永远看不见它——
    实测里它表现为一次烧了 23 秒、产出为零、错误信息还指错方向的调用。

    判据来自服务端的 `finish_reason == "length"`，不是拿 token 数去猜。
    """

    def __init__(self, tokens: int) -> None:
        """记下被切断时已经吐了多少 token。"""
        super().__init__(f"output hit the token limit at {tokens} tokens and was cut off")
        self.tokens = tokens


class MaxRetriesExceeded(AgentError):
    """连续重试仍拿不到合法动作。

    到这一步说明模型在当前状态下持续失败，是一条要进 trace 并被 replay 统计的失败模式，
    不是"再试试就好"。
    """

    def __init__(self, attempts: int, last_reason: str) -> None:
        """记下试了几次、最后一次为什么失败。"""
        super().__init__(f"gave up after {attempts} attempts, last: {last_reason}")
        self.attempts = attempts
        self.last_reason = last_reason


class ToolTimeout(AgentError):
    """外部提供者（模型网关/API）调用不通——网络层或服务端 5xx，重试后仍失败。

    和 `ParseFailure` 分开：那是"调通了但输出没法用"，这是"根本没调通"。
    replay 里它们指向不同修法：前者改 prompt/解析，后者查网关/配额。

    **归 `AgentError` 家族是关键**：`RunHarness.dispatch` 只捕 `AgentError`——
    网络抖动重试后仍失败，应该让**这一局失败**（由 run 级重试预算接管），
    而不是一路穿过让整个 run 崩掉。

    **4xx（401/403/400）不在这里**：那是配置/请求错误，不是抖动，重试多少次
    都一样，必须当场崩（装配期就该暴露）。
    """


class DecisionAttemptFailed(AgentError):
    """一次决策尝试失败（解析不出/幻觉了动作/被截断）。

    **单次尝试**的失败，可重试；账（`ModelCall`）随异常带出来，调用方
    （Harness）决定要不要再问一次、以及重试预算耗尽后升不升级成
    `MaxRetriesExceeded`。和 `MaxRetriesExceeded` 分开正是因为"这一次没成"
    和"这一步彻底完了"是循环控制者才知道的两件事，大脑不该替它下判断
    （见 `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"）。
    """

    def __init__(self, call: ModelCall) -> None:
        """记下这次失败的账单。"""
        super().__init__(f"decision attempt failed: {call.error_kind}: {call.error}")
        self.call = call


class PlanAttemptFailed(AgentError):
    """一次 run 级规划尝试失败（解析不出 `RunPlan`）。

    **单次尝试**的失败，可重试；账（`ModelCall`）随异常带出来，调用方
    （`RunHarness`）决定要不要再问一次、以及重试预算耗尽后怎么收场——跟
    `DecisionAttemptFailed` 是同一个模式在 run 级图上的落地（"谁控制循环，
    谁记账"，见 `docs/ROADMAP.md` "重试循环该不该从 brain 挪到 harness"）。
    """

    def __init__(self, call: ModelCall) -> None:
        """记下这次失败的账单。"""
        super().__init__(f"plan attempt failed: {call.error_kind}: {call.error}")
        self.call = call


class PerceptionAttemptFailed(AgentError):
    """一次感知尝试失败（视觉模型输出解析不出 `ScreenState`）。

    **单次尝试**的失败，可重试；账（普通 dict，字段同 `ModelCall.payload`）
    随异常带出来。和 `PerceptionFailure` 分开：那是重试预算耗尽后的升级态，
    这里只是"问一次没读出来"。
    """

    def __init__(self, call: dict[str, str]) -> None:
        """记下这次失败的账单。"""
        super().__init__(f"perception attempt failed: {call.get('raw', '')[:200]!r}")
        self.call = call


class ImageNotDelivered(AgentError):
    """图片没有真的送到模型，但网关装作一切正常。

    实测于 DashScope 的 Anthropic 兼容端点：带 image block 的请求被接受、不报错、
    返回一段读起来合理的描述，而模型压根没收到图——描述是从提示词里的几个字
    凭空编出来的。

    **走异常而不是 assert**：这是"外部世界不配合"，不是调用方违约（CLAUDE.md 第八节）。
    调用方没做错任何事，是网关的行为。

    **单独成一类而不是并进别的错误**：它在 replay 里是独立的失败模式，
    而且是唯一一个"不修就会让全部实验数据静默作废"的那种。
    统计里必须一眼能看见它，混进 ParseFailure 就被淹了。

    判据是 token 数不是回答内容：模型怎么答不能说明图有没有到，
    输入 token 塌回纯文本量级就是铁证。
    """

    def __init__(self, input_tokens: int, floor: int) -> None:
        """记下实际输入 token 数与判定下界。"""
        super().__init__(
            f"image was silently dropped: input_tokens={input_tokens} < floor={floor}; "
            "the model never saw the image and its answer is a hallucination"
        )
        self.input_tokens = input_tokens
        self.floor = floor


class PerceptionFailure(AgentError):
    """反复调用视觉模型仍拿不到能解析的 `ScreenState`。

    和 `ParseFailure` 分开：那是**大脑**的输出格式问题（改 prompt 或上约束解码），
    这是**感知层**的（换模型、改预处理、或者这一帧本来就没法读）。
    在 replay 里它们指向完全不同的修法，合并就丢了诊断信息。

    与 `ImageNotDelivered` 也分开：那是图没送到（网关问题），
    这是图送到了但读不出结构（能力问题）。
    """

    def __init__(self, attempts: int, last_reason: str) -> None:
        """记下试了几次、最后一次为什么失败。"""
        super().__init__(f"perception failed after {attempts} attempts: {last_reason}")
        self.attempts = attempts
        self.last_reason = last_reason
