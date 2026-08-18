"""FakeLLM —— 脚本化的 LLMProvider，**不做任何推理**。

它是 mock 而不是实现：真实 provider 会思考，它只会照本宣科。
存在的意义是让整个 ReAct 循环变成**确定性**的——同一个脚本跑一百遍结果完全一样，
测试才能断言精确结果，也才能零成本地反复跑。

刻意支持"返回坏 JSON"：解析失败与重试是大脑最重要的一条分支，
没有能制造失败的 mock 就测不到它。
"""

from __future__ import annotations

import json

from pokemon_agent.interfaces.llm import Completion


class FakeLLM:
    """按预设脚本逐条返回文本。

    用法见 tests/test_react.py。两种构造方式：
    - `FakeLLM(["...", "..."])`：直接给原始文本，想给什么给什么（包括坏 JSON）。
    - `FakeLLM.scripted([("思考", "动作名"), ...])`：给合法动作序列，自动包成 JSON。
    """

    def __init__(self, responses: list[str], *, loop: bool = False) -> None:
        """
        前置条件：responses 非空。
        loop=True 时脚本用尽后从头循环——用于"一直选同一个动作直到任务完成"这类场景。
        """
        assert responses, "FakeLLM needs at least one scripted response"

        self._responses = list(responses)
        self._loop = loop
        self._calls = 0

    @classmethod
    def scripted(cls, steps: list[tuple[str, str]], *, loop: bool = False) -> FakeLLM:
        """从 (thought, action) 序列构造，省得测试里手写 JSON。

        `rationale` 自动取 thought 本身：脚本化的 mock 里"想法"就是"理由"，
        没有第三方信息可编。**要测 rationale 本身的行为，用原始文本构造方式**
        （`FakeLLM([...])`），别在这里加参数——那会让所有只关心动作序列的测试
        都被迫写一遍论据。
        """
        texts = [
            json.dumps(
                {"thought": thought, "rationale": [thought], "action": action, "args": {}},
                ensure_ascii=False,
            )
            for thought, action in steps
        ]
        return cls(texts, loop=loop)

    @property
    def call_count(self) -> int:
        """被调用了几次。测试用它断言重试确实发生了。"""
        return self._calls

    def complete(self, prompt: str) -> Completion:
        """按脚本返回下一条。

        前置条件：prompt 非空（与 LLMProvider 契约一致）。
        失败：脚本用尽且未开 loop 时抛 IndexError——这是**测试写错了**，
            不是运行时情况，所以故意让它爆炸而不是返回兜底值。
        """
        assert prompt, "complete() got an empty prompt"

        index = self._calls % len(self._responses) if self._loop else self._calls
        self._calls += 1
        if index >= len(self._responses):
            raise IndexError(
                f"FakeLLM script exhausted after {len(self._responses)} responses; "
                "the test asked for more LLM calls than it scripted"
            )

        text = self._responses[index]
        # token 数用长度粗估：成本统计的链路要能跑通，数值本身在 mock 里没有意义。
        return Completion(
            text=text, prompt_tokens=len(prompt) // 4, completion_tokens=len(text) // 4
        )
