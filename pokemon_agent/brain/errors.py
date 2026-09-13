"""brain 的内部失败：模型调不通 / 输出解析不出 / 幻觉了动作 / 被截断。

划分依据（CLAUDE.md 第八节）：**调用方违约用 assert，外部世界不配合用这里的异常。**
每类失败有名字，是因为 replay 要按失败类型归类统计——
"修了 Z 类失败模式"这句话的 Z 就是这里的类数。

**为什么这些异常住在 `brain/` 而不是顶层 `errors.py`**（0913 定案）：
它们是 **brain 的内部词汇**——`ParseFailure`/`IllegalAction`/`OutputTruncated`
描述的是"大脑吐出来的东西为什么不能用"，`AttemptFailed` 家族是 brain 六方法的
唯一失败出口。brain 是要能**被整体拷走复用**的模块（跟 `memory/` 同一规格），
它的词汇得跟着它走，不能留在项目顶层等别人施舍。

**根异常是 `BrainError`，不是顶层的 `AgentError`**（0913 深夜十一修正）：
此前这六个类继承 `pokemon_agent.errors.AgentError`，理由是"`RunHarness.dispatch`
只捕 `AgentError`，靠这个共同祖先让单局失败不炸掉整个 run"。**那条理由不成立**——
实测：这些异常**一出生就被 `BrainTool._attempt_loop` 的 `except AttemptFailed`
接住**，翻译成 `MaxRetriesExceeded`（那才是 tool 抛、harness 接的跨层升级态）。
换句话说 **brain 的异常从来走不到 harness 面前**，"共同祖先"是纯仪式。
留一个从外部模块继承的根，等于让 brain 拷走后**必须带上本项目顶层的
`errors.py`** 才能跑——第三方可替换性当场破功。
现在 `BrainError(Exception)` 自持：brain 的整条错误家族不再引用外部任何东西。

**跟 `AgentError` 的分工**（两者不再有继承关系，靠 tool 层做桥）：
`BrainError` 是"脑子内部这次没成"，`AgentError` 是"本项目预期内的失败"
（含 tool 层的 `MaxRetriesExceeded`、world 的感知失败）。桥在
`tools/brain_tool.py`：它 `except AttemptFailed`（brain 的）→ 重试 →
耗尽抛 `MaxRetriesExceeded`（顶层的）。**翻译点唯一**，
两个模块谁都不认识对方的异常根。
"""

from __future__ import annotations

from .interface.domain.model_call import ModelCall


class BrainError(Exception):
    """brain 内部预期内失败的基类。

    **它只服务 brain**：捕获它意味着"我知道大脑这里会出问题"。它**不是**项目
    级的共同祖先（那是 `pokemon_agent.errors.AgentError`）——两者刻意不建立
    继承关系，因为 brain 要能被整体拷走，不能欠外部一个基类。
    跨模块的翻译发生在 tool 层（见模块 docstring 的"桥"一段）。
    """


class ParseFailure(BrainError):
    """LLM 输出无法解析成 Action。

    这是**最常见**的一类，且是可重试的。带上原始文本，因为 replay 时要看模型到底吐了什么。
    """

    def __init__(self, raw_text: str, reason: str) -> None:
        """记下模型吐了什么、为什么解析不了。"""
        super().__init__(f"{reason}: {raw_text!r}")
        self.raw_text = raw_text
        self.reason = reason


class IllegalAction(BrainError):
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


class OutputTruncated(BrainError):
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


class ToolTimeout(BrainError):
    """外部提供者（模型网关/API）调用不通——网络层或服务端 5xx，重试后仍失败。

    和 `ParseFailure` 分开：那是"调通了但输出没法用"，这是"根本没调通"。
    replay 里它们指向不同修法：前者改 prompt/解析，后者查网关/配额。

    **它服务的是 brain 的链路**：抛它的是 `brain/providers.py` 的
    `complete()`/`describe()`（那个文件 0913 从顶层 `providers/` 搬来）。
    放在 brain 内部是因为"模型调不通"这条语义对 brain 六条链路成立。

    **4xx（401/403/400）不在这里**：那是配置/请求错误，不是抖动，重试多少次
    都一样，必须当场崩（装配期就该暴露）。

    **进 brain 的错误家族就不必再挂 `AgentError`**：它永远在
    `BrainTool._attempt_loop` 里被接住、翻译成 `MaxRetriesExceeded` 再上抛，
    走不到 harness 的捕获点。
    """


class ImageNotDelivered(BrainError):
    """图片没有真的送到模型，但网关装作一切正常。

    实测于 DashScope 的 Anthropic 兼容端点：带 image block 的请求被接受、不报错、
    返回一段读起来合理的描述，而模型压根没收到图——描述是从提示词里的几个字
    凭空编出来的。

    **走异常而不是 assert**：这是"外部世界不配合"，不是调用方违约（CLAUDE.md 第八节）。
    调用方没做错任何事，是网关的行为。

    **单独成一类而不是并进别的错误**：它在 replay 里是独立的失败模式，
    而且是唯一一个"不修就会让全部实验数据静默作废"的那种。
    统计里必须一眼能看见它，混进 `ParseFailure` 就被淹了。

    判据是 token 数不是回答内容：模型怎么答不能说明图有没有到，
    输入 token 塌回纯文本量级就是铁证。

    **为什么归 brain**（0913 深夜十一）：**谁抛的归谁**。它由
    `brain/providers.py` 的 `_MultimodalMixin.describe()` 抛出——那是 brain 的
    实现文件（0913 从顶层 `providers/openai_compatible.py` 搬进来）。放在 brain
    内部之后，brain 拷走时**不再欠任何外部文件**（此前它住顶层 `errors.py`，
    拷走 brain 就得连那个文件一起带，第三方可替换性破功）。

    **world 的感知链怎么办**：world 的 `describe()` 也走这同一份实现（它拿
    一个 `QwenProvider` 当 `VisionProvider`），于是也可能收到这个异常。world
    **不 import 它**——`world/pyboy_world.py` 在 `describe()` 外面把任何失败
    （含这个）就地包成 world 自己的 `PerceptionAttemptFailed`，
    world 的失败出口因此仍然只有自己那两个类（见 `world/errors.py`）。
    **两个模块各自成立，桥在"谁调谁包"这一层**，不是共享一个异常类。
    """

    def __init__(self, input_tokens: int, floor: int) -> None:
        """记下实际输入 token 数与判定下界。"""
        super().__init__(
            f"image was silently dropped: input_tokens={input_tokens} < floor={floor}; "
            "the model never saw the image and its answer is a hallucination"
        )
        self.input_tokens = input_tokens
        self.floor = floor


class AttemptFailed(BrainError):
    """**一次尝试**失败——模型调不通 / 输出解析不出 / 动作幻觉 / 被截断。

    家族基类，本身不直接抛。**这个家族的成员是 brain 六方法的唯一失败出口**：
    brain 不做重试（重试循环在 `BrainTool`），所以"这一次没成"必须作为一种
    可预期的结果交给调用方——异常携带这次的 `call`（账），tool 收进自己的
    重试账里，预算耗尽再升级成 `MaxRetriesExceeded`。

    **`call` 的类型是 brain 那份 `ModelCall`**（`brain.interface.ModelCall`）：
    brain 只认识自己的方言，不认识 tool 层的工作形状——`BrainTool` 收账时
    做一次三个字段的翻译（`_adopt()`）。

    **为什么按链路分子类而不是一个类加 `source` 字段**：`brain` 是第三方模块
    的视角，"这条链路出了什么问题"用类型表达，调用方 `except` 一下就够了；
    塞进字段则每个调用方都要 `if` 分支解析，多一层运行时判断。
    六个子类各自对应 `BrainPort` 的一个方法，一一对得上。

    与 `MaxRetriesExceeded` 的分工：这里是"这一次没成"（可重试），
    那里是"这一步彻底完了"（预算耗尽）——**循环控制者才知道自己是哪一种**，
    所以后者由 tool 抛，不由 brain 抛。
    """

    def __init__(self, call: ModelCall, source: str = "") -> None:
        """记下这次失败的账单与它属于哪条链路。"""
        super().__init__(
            f"[{source or type(self).__name__}] attempt failed: "
            f"{call.error_kind}: {call.error}"
        )
        self.call = call
        self.source = source


class DecisionAttemptFailed(AttemptFailed):
    """一次决策尝试失败（解析不出动作 / 幻觉了按键 / 被截断）。

    可重试；`choose()` 的下一次尝试会**叠加纠正说明**（把上次错在哪拼进 prompt），
    所以重试本身携带信息增量。
    """

    def __init__(self, call: ModelCall, source: str = "decide") -> None:
        """记下这次失败的账单。"""
        super().__init__(call, source)


class PlanAttemptFailed(AttemptFailed):
    """一次 run 级规划尝试失败（解析不出 `RunPlan`）。

    可重试；但 `run_plan` 的重试是**原样重问**（不叠加纠正说明），
    所以 tool 侧没有 `retry_prompt` 这一步。
    """

    def __init__(self, call: ModelCall, source: str = "plan") -> None:
        """记下这次失败的账单。"""
        super().__init__(call, source)


class JudgeAttemptFailed(AttemptFailed):
    """一次判定尝试失败（模型调不通 / 输出不是合法裁决）。

    **此前这里不抛异常，而是静默返回 `done=False`**——理由是"判定器坏掉不该让整局崩"。
    改成抛之后那条理由由 tool 的重试预算承接：先重试三次，仍失败则
    `MaxRetriesExceeded` 上抛，harness 的调用点决定怎么收场。
    静默降级的问题在于**它把"判定器坏了"和"真的没达成"混成同一个结果**——
    trace 里表现为成功率悄悄变 0，而"判定失效"这件事在数据里看不见。
    """

    def __init__(self, call: ModelCall, source: str = "judge") -> None:
        """记下这次失败的账单。"""
        super().__init__(call, source)


class VerifyAttemptFailed(AttemptFailed):
    """一次校验尝试失败（模型调不通 / 输出解析不出）。

    **此前这里不抛异常，而是把所有条目标成不可靠返回**。改抛之后
    （2026-09-13 取消降级），"全部标不可靠"这份保守结果**不再由任何一层自动产出**
    ——它与"这一局的记忆确实都不可信"在数据上无法区分，会把"校验器坏了"伪装成
    业务结论。现在：`BrainTool` 重试 `BRAIN_MAX_ATTEMPTS` 次仍失败就抛
    `MaxRetriesExceeded(source="verify")`，**harness 的调用点决定要不要给保守结果**
    （要给的话也发生在它的 `except` 里，trace 上看得见）。

    `verify._parse_verify` 仍会返回一份补齐的保守列表，但它**放在异常旁边**、
    由调用方决定用不用，`brain` 自己不消费。
    """

    def __init__(self, call: ModelCall, source: str = "verify") -> None:
        """记下这次失败的账单。"""
        super().__init__(call, source)


class SummarizeAttemptFailed(AttemptFailed):
    """一次蒸馏尝试失败（模型调不通 / 输出解析不出）。

    **此前这里不抛异常，而是返回 `summary=None`**。改抛之后（2026-09-13 取消降级），
    "这次没蒸出东西"不再是一种正常返回——`BrainTool` 重试耗尽就抛
    `MaxRetriesExceeded(source="summarize")`，由 harness 的调用点决定怎么收场
    （跟 `verify` 同一个处理）。
    """

    def __init__(self, call: ModelCall, source: str = "summarize") -> None:
        """记下这次失败的账单。"""
        super().__init__(call, source)


__all__ = [
    "AttemptFailed",
    "BrainError",
    "DecisionAttemptFailed",
    "IllegalAction",
    "ImageNotDelivered",
    "JudgeAttemptFailed",
    "OutputTruncated",
    "ParseFailure",
    "PlanAttemptFailed",
    "SummarizeAttemptFailed",
    "ToolTimeout",
    "VerifyAttemptFailed",
]
