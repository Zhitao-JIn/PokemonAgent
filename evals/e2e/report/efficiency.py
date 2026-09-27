"""效率层（spec §十）：按链路拆的 token 与调用次数、失败与耗尽次数、按键、局数、task 数、墙钟。"""

from __future__ import annotations

from evals.e2e.checks import RunStream
from evals.e2e.schemas import Efficiency, TokenUse
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.tools.trace import MODEL_CALL_KINDS
from pokemon_agent.tools.trace.content import ModelCallContent


def efficiency(stream: RunStream) -> Efficiency:
    """整个 run（这条执行线）的开销。"""
    tokens: dict[str, TokenUse] = {}
    calls: dict[str, int] = {}
    for e in stream.of_kind(*MODEL_CALL_KINDS):
        assert isinstance(e.content, ModelCallContent)
        link = e.kind.removesuffix("_call")
        use = tokens.setdefault(link, TokenUse())
        use.input += e.content.input_tokens
        use.output += e.content.output_tokens
        use.cached += e.content.cached_tokens
        use.reasoning += e.content.reasoning_tokens
        calls[link] = calls.get(link, 0) + 1
    times = [e.ts for e in stream.events]
    return Efficiency(
        tokens_by_link=tokens,
        calls_by_link=calls,
        call_failed=len(stream.of_kind(TraceKind.CALL_FAILED)),
        call_exhausted=len(stream.of_kind(TraceKind.CALL_EXHAUSTED)),
        presses=len(stream.of_kind(TraceKind.PRESS_KEY)),
        episodes=len(stream.of_kind(TraceKind.EPISODE_START)),
        tasks=len(stream.of_kind(TraceKind.TASK_START)),
        wall_seconds=round(max(times) - min(times), 3) if times else 0.0,
    )


__all__ = ["efficiency"]
