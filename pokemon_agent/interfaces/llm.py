"""LLM 提供方接口。

存在的意义：代码里**任何地方都不许直连模型 SDK**（CLAUDE.md 第六节）。
当前唯一的实现是 `providers/dashscope.QwenText`，换模型只改装配处的一行。

返回值 `Completion` 在 `schemas/completion.py`——**这里只放 Protocol**，
数据模型归 `schemas/`（CLAUDE.md 第四节）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.completion import Completion


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

        把一段 prompt 交给文本模型，换回补全结果和 token 账。
        """
        ...
