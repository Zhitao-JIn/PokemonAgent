"""LLM 提供方接口。

存在的意义：代码里**任何地方都不许直连模型 SDK**（CLAUDE.md 第六节）。
当前唯一的实现是 `providers/dashscope.QwenText`，换模型只改装配处的一行。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class Completion(BaseModel):
    """一次补全的结果。

    把 token 数放进返回值而不是让调用方去查，是为了成本统计能在**调用点**就地产出 trace，
    不需要 LLM 实现和成本模块互相认识。
    """

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    truncated: bool = False
    """输出是不是被 max_tokens 截断了。

    **必须由 provider 给，不能让调用方猜。** 调用方不知道 max_tokens 是多少，
    只能拿 `completion_tokens == 某个整数` 去猜，那是巧合不是判据。

    为什么值得单开一个字段：截断在下游表现为"JSON 少了个右括号"，
    和"模型不会写 JSON"长得一模一样，但**修法完全相反**——
    前者要调大 max_tokens 或让模型少说，后者要改 prompt 或上约束解码。
    混成一类 ParseFailure，统计里就永远看不见它。
    """


@runtime_checkable
class LLMProvider(Protocol):
    """把 prompt 变成文本的东西。故意做得很薄。

    不放进这个接口的东西，以及原因：
    - **重试**：属于调用方的策略（大脑要按解析失败重试，并计数进 trace），不是 provider 的事。
    - **结构化输出 / 约束解码**：原型期用 Pydantic 解析 + 重试代替；
      真上约束解码时应当加一个**新方法**而不是改这个方法的语义。
    - **对话历史**：大脑无状态（铁律 1），历史由调用方每次组装完整传入。
    """

    def complete(self, prompt: str) -> Completion:
        """对 prompt 做一次补全。

        前置条件：prompt 非空。
        后置条件：返回的 text 可能是任意字符串（**包括不合法的 JSON**）——
            解析失败是预期内的运行时情况，由调用方处理，本方法不为格式负责。
        失败：底层不可用时抛异常，不返回空 Completion。
            "调不通"和"调通了但输出没用"必须能被调用方区分开。
        """
        ...
