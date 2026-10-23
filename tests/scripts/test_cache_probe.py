"""缓存专项请求形状与请求预算，全部使用 HTTP 替身。"""

from __future__ import annotations

import pytest
from _doubles.http import FakeUrlopen, ok_body

from scripts import probe_models as probe


def test_cache_trials_are_twelve_text_requests_with_fixed_modes() -> None:
    items = probe.candidates("all", cache_only=True)

    trials = probe.trials(items)

    assert len(trials) == 12
    assert all(kind == "text" for _, kind, _ in trials)
    assert all(not item.thinking for item in items)
    assert items[0].cache_marker == probe.MARKER
    assert items[1].name == "c2_split"


def test_cache_requests_use_stable_boundaries_and_small_output_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-claude")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai")
    fake = FakeUrlopen(body={"content": [{"type": "text", "text": "ok"}]})
    monkeypatch.setattr("urllib.request.urlopen", fake)
    claude, openai = probe.candidates("all", cache_only=True)

    probe.call(claude, claude.build(), "text", 1)
    fake.next_body = ok_body()
    provider = openai.build()
    probe.call(openai, provider, "text", 1)
    probe.call(openai, provider, "text", 2)

    first = fake.calls[0]["json"]
    assert first["max_tokens"] == 256
    assert first["messages"][0]["content"] == [
        {"type": "text", "text": probe.PREFIX, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": probe.MARKER + "1"},
    ]
    second, third = [call["json"] for call in fake.calls[1:]]
    assert second["max_completion_tokens"] == 256
    assert (
        second["messages"][0]
        == third["messages"][0]
        == {"role": "developer", "content": probe.PREFIX}
    )
    assert second["messages"][1]["content"] == probe.MARKER + "1"
    assert third["messages"][1]["content"] == probe.MARKER + "2"
