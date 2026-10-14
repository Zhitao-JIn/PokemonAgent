"""A2 agent：seed/turn/close 状态机 + `_parse` 审/插话解析（用 fake provider，不联网）。"""

from __future__ import annotations

from pokemon_agent.agent_reviewer.agent import AgentReviewer, _parse
from pokemon_agent.agent_reviewer.provider import LlmResult
from pokemon_agent.schemas.agent_reviewer.communication import ChatTurn
from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict
from pokemon_agent.schemas.review_backend.communication.FromReviewBackendToFrontendAskReq import (
    FromReviewBackendToFrontendAskReq,
)


class FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete(self, prompt: str) -> LlmResult:
        self.calls += 1
        return LlmResult(self.text, 1, 1, 0, 0)

    def describe(self, prompt: str, images: list[str]) -> LlmResult:
        self.calls += 1
        return LlmResult(self.text, 1, 1, 0, 0)


def _ask(seq: int = 1, kind: str = "audit", body: str = "b") -> FromReviewBackendToFrontendAskReq:
    return FromReviewBackendToFrontendAskReq(
        seq=seq, run_id="r", kind=kind, prompt="p", body=body, deadline=None
    )


def test_seed_builds_conversation_and_returns_proposal() -> None:
    agent = AgentReviewer(llm=FakeLLM("认账"))
    prop = agent.seed(_ask(), frame=None)
    # 默认 ACCEPT（"认账"命中认账词）。
    assert prop.verdict == AuditVerdict.ACCEPT
    assert "1" in agent._convs  # seq 字符串化


def test_turn_appends_delta_and_rerenders() -> None:
    fake = FakeLLM("推翻：看错了")
    agent = AgentReviewer(llm=fake)
    agent.seed(_ask(), frame=None)
    before = len(agent._convs["1"])
    prop = agent.turn("1", ChatTurn(role="human", text="再想想"), frame=None)
    # 先 append 人的 delta，再 _call 里 append agent 自己的结论 → +2。
    assert len(agent._convs["1"]) == before + 2
    assert prop.verdict == AuditVerdict.OVERTURN
    assert "看错了" in prop.note


def test_close_releases_seq() -> None:
    agent = AgentReviewer(llm=FakeLLM("认账"))
    agent.seed(_ask(), frame=None)
    agent.close(1)
    assert "1" not in agent._convs
    # close 之后再 turn 不再追加（返回空）。
    prop = agent.turn("1", ChatTurn(role="human", text="x"), frame=None)
    assert prop.text is None and prop.verdict is None


def test_parse_audit_overturn_and_accept_and_default() -> None:
    assert _parse("我推翻这个结论，理由：画面里没到", "audit").verdict == AuditVerdict.OVERTURN
    assert _parse("同意，达成", "audit").verdict == AuditVerdict.ACCEPT
    # 取不到明确词 → 默认 ACCEPT（误判"没成"代价小）。
    assert _parse("这局打得还行", "audit").verdict == AuditVerdict.ACCEPT


def test_parse_inject_text_or_none() -> None:
    assert _parse("建议往北走", "inject").text == "建议往北走"
    # 空文本 → None（"无意见"）。
    assert _parse("", "inject").text is None
