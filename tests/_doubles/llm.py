"""`Brain` 单元测试共用的脚本化假 provider（手写，不用 MagicMock）。

`Brain.choose`（以及后面 plan / judge / verify 目录的测试）需要一个按脚本回话的假
provider，证明「模型怎么写、大脑怎么读」——这里不连网、不调真实模型、不读 ROM。手写
小类比 `MagicMock` 更贴合 AGENTS.md「不写 mock 套 mock」：每个方法的行为一眼可见，
还能像真 provider 一样用 `.requests` / `.described` 记下每次收到的请求，供测试断言
「prompt 是否原样到达」「带图时走没走 describe」。
"""

from __future__ import annotations

from typing import cast

from pokemon_agent.brain.schemas import (
    LlmCompleteReq,
    LlmCompleteResp,
    VisionDescribeReq,
    VisionDescribeResp,
)

# `replies` 里既能放响应也能放异常：异常实例在消费到时按原样抛出。
Reply = LlmCompleteResp | VisionDescribeResp | BaseException


def text_reply(
    text: str,
    *,
    truncated: bool = False,
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
    cached_tokens: int = 3,
    reasoning_tokens: int = 2,
) -> LlmCompleteResp:
    """一行造一份完整文本补全响应，token 字段给默认值，免得每个测试重写一遍。"""
    return LlmCompleteResp(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
        truncated=truncated,
    )


def vision_reply(
    text: str,
    *,
    input_tokens: int = 21,
    output_tokens: int = 9,
    cached_tokens: int = 4,
    reasoning_tokens: int = 5,
) -> VisionDescribeResp:
    """一行造一份完整视觉描述响应，token 字段给默认值，免得每个测试重写一遍。"""
    return VisionDescribeResp(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


class ScriptedLLM:
    """按脚本回话的假 `LLMProvider`：`complete()` 按顺序消费回复。

    `multimodal` 是构造参数（默认 `False`），`Brain.choose` 查它决定带图时走
    `describe()` 还是退化成纯文本。回复里放 `BaseException` 实例时按原样抛出，
    用尽后再被调用抛 `AssertionError`。
    """

    def __init__(self, *replies: Reply, multimodal: bool = False) -> None:
        self.multimodal = multimodal
        self._replies: list[Reply] = list(replies)
        self.requests: list[LlmCompleteReq] = []

    def complete(self, req: LlmCompleteReq) -> LlmCompleteResp:
        """记下这次请求，再按脚本回下一条回复（异常则抛出）。"""
        self.requests.append(req)
        return cast(LlmCompleteResp, self._pop())

    def _pop(self) -> Reply:
        if not self._replies:
            raise AssertionError("ScriptedLLM ran out of replies")
        reply = self._replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class ScriptedJudge(ScriptedLLM):
    """在 `ScriptedLLM` 上加 `describe()`，满足 `JudgeProvider`。

    `Brain.choose` 带图且模型多模态时调 `describe()`，所以决策位置也要能放它。
    """

    def __init__(self, *replies: Reply, multimodal: bool = False) -> None:
        super().__init__(*replies, multimodal=multimodal)
        self.described: list[VisionDescribeReq] = []

    def describe(self, req: VisionDescribeReq) -> VisionDescribeResp:
        """记下这次请求，再按脚本回下一条回复（异常则抛出）。"""
        self.described.append(req)
        return cast(VisionDescribeResp, self._pop())
