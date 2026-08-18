"""预期内的失败。

划分依据（CLAUDE.md 第八节）：**调用方违约用 assert，外部世界不配合用这里的异常。**
每类失败有名字，是因为 replay 要按失败类型归类统计——
"修了 Z 类失败模式"这句话的 Z 就是这里的类数。
"""

from __future__ import annotations


class AgentError(Exception):
    """本项目所有预期内失败的基类。捕获它意味着"我知道这里会出问题"。"""


class ParseFailure(AgentError):
    """LLM 输出无法解析成 Action。

    这是**最常见**的一类，且是可重试的。带上原始文本，因为 replay 时要看模型到底吐了什么。
    """

    def __init__(self, raw_text: str, reason: str) -> None:
        super().__init__(f"{reason}: {raw_text[:200]!r}")
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
        super().__init__(f"action {name!r} not in action space {allowed}")
        self.name = name
        self.allowed = allowed


class MaxRetriesExceeded(AgentError):
    """连续重试仍拿不到合法动作。

    到这一步说明模型在当前状态下持续失败，是一条要进 trace 并被 replay 统计的失败模式，
    不是"再试试就好"。
    """

    def __init__(self, attempts: int, last_reason: str) -> None:
        super().__init__(f"gave up after {attempts} attempts, last: {last_reason}")
        self.attempts = attempts
        self.last_reason = last_reason


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
        super().__init__(
            f"image was silently dropped: input_tokens={input_tokens} < floor={floor}; "
            "the model never saw the image and its answer is a hallucination"
        )
        self.input_tokens = input_tokens
        self.floor = floor
