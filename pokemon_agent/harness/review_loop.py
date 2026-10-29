"""单次规划的临时重问图：轮次只在本次调用内流转，不进入三层存档。"""

import sys
from collections.abc import Callable
from typing import Any, TypeVar, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain import ReviewMark

Outcome = TypeVar("Outcome", bound=BaseModel)


class ReviewRound(BaseModel):
    """一次亮表的轮次与连续 AI 生效计数；调用方按此生成请求及账。"""

    number: int = Field(ge=1)
    consecutive_agent_rounds: int = Field(ge=0)
    max_agent_rounds: int = Field(ge=0)


class _LoopState(BaseModel):
    outcome: BaseModel | None = None
    note: str = ""
    round: int = 0
    agent_rounds: int = 0
    done: bool = False


def elicit_with_review(
    ask_brain: Callable[[str, int], Outcome],
    ask_reviewer: Callable[[Outcome, ReviewRound], ReviewMark],
    *,
    max_agent_rounds: int,
) -> tuple[Outcome, str]:
    """问脑、亮表，有有效意见就重问；返回定稿及上一轮实际生效的意见。

    前置条件：上限非负；ask_reviewer 按 ReviewRound 标注 capped 并记录每次真实询问。
    人的意见清零连续 AI 计数；空回话、默认回话或 capped 结束。本层不吞回调异常。
    后置条件：连续 AI 生效次数不超过上限；临时图不持久化、不限制人的插话次数。
    """
    assert max_agent_rounds >= 0, "negative agent review limit"
    graph = _build_loop(ask_brain, ask_reviewer, max_agent_rounds)
    result = graph.invoke(_LoopState(), {"recursion_limit": sys.maxsize}, durability="exit")
    assert result["outcome"] is not None, "review loop ended without an outcome"
    assert result["agent_rounds"] <= max_agent_rounds, "agent review limit exceeded"
    return cast(Outcome, result["outcome"]), result["note"]


def _build_loop(
    ask_brain: Callable[[str, int], Outcome],
    ask_reviewer: Callable[[Outcome, ReviewRound], ReviewMark],
    max_agent_rounds: int,
) -> CompiledStateGraph:
    """只调度本次重问的 ask/review。"""

    def ask(state: _LoopState) -> dict[str, Any]:
        number = state.round + 1
        return {"outcome": ask_brain(state.note, number), "round": number}

    def review(state: _LoopState) -> dict[str, Any]:
        assert state.outcome is not None
        rounds = ReviewRound(
            number=state.round,
            consecutive_agent_rounds=state.agent_rounds,
            max_agent_rounds=max_agent_rounds,
        )
        mark = ask_reviewer(cast(Outcome, state.outcome), rounds)
        if not mark.reply or mark.by == "none" or mark.capped:
            return {"done": True}
        count = state.agent_rounds + 1 if mark.by == "agent" else 0
        assert count <= max_agent_rounds, "review callback failed to cap agent feedback"
        return {"note": mark.reply, "agent_rounds": count}

    graph = StateGraph(_LoopState)
    graph.add_node("ask", ask)
    graph.add_node("review", review)
    graph.add_edge(START, "ask")
    graph.add_edge("ask", "review")
    graph.add_conditional_edges("review", lambda state: END if state.done else "ask")
    return graph.compile()
