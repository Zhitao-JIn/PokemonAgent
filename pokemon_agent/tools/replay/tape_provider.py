"""`TapeProvider`：回放段里顶替大模型——按序吐出录下的原文（或重抛录下的失败），先核 prompt。

它在最底层（`LLMProvider` / 带 `describe` 的视觉 provider）顶替，所以 brain 的解析、重试与记账
照常走一遍：录下的原文解析出的就是当初的结果，录下的失败照样触发重试或耗尽。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.brain.schemas.completion import LlmCompleteReq, LlmCompleteResp
from pokemon_agent.brain.schemas.vision import VisionDescribeReq, VisionDescribeResp

from .tape import RecordedCall, Tape

_TRUNCATED = "OutputTruncated"


class TapeProvider:
    """包一个真 provider：切换前从磁带取，切换后原样转给它；其余属性（如 `multimodal`）照转。"""

    def __init__(self, real: Any, tape: Tape) -> None:  # noqa: ANN401 —— 任一种 provider
        self._real = real
        self._tape = tape

    def complete(self, req: LlmCompleteReq) -> LlmCompleteResp:
        if self._tape.switched:
            return self._real.complete(req)
        call = self._recorded(req.prompt)
        p = call.payload
        return LlmCompleteResp(
            text=p["raw"],
            prompt_tokens=int(p.get("input_tokens", 0)),
            completion_tokens=int(p.get("output_tokens", 0)),
            cached_tokens=int(p.get("cached_tokens", 0)),
            reasoning_tokens=int(p.get("reasoning_tokens", 0)),
            truncated=call.error_kind == _TRUNCATED,
        )

    def describe(self, req: VisionDescribeReq) -> VisionDescribeResp:
        if self._tape.switched:
            return self._real.describe(req)
        p = self._recorded(req.prompt).payload
        return VisionDescribeResp(
            text=p["raw"],
            input_tokens=int(p.get("input_tokens", 0)),
            output_tokens=int(p.get("output_tokens", 0)),
            cached_tokens=int(p.get("cached_tokens", 0)),
            reasoning_tokens=int(p.get("reasoning_tokens", 0)),
        )

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self._real, name)

    def _recorded(self, prompt: str) -> RecordedCall:
        """取下一次录下的调用；录下的是"没调通"（没有原文）就重抛同名异常。"""
        call = self._tape.next_call(prompt)
        if "raw" not in call.payload:
            raise type(call.error_kind or "ReplayedFailure", (Exception,), {})(call.error)
        return call


__all__ = ["TapeProvider"]
