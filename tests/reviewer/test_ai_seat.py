import pytest
from pydantic import ValidationError

from pokemon_agent.reviewer.seats.ai.seat import _AiInjectAnswer


def test_ai_inject_proposal_requires_nonempty_text() -> None:
    for text in ("", "   "):
        with pytest.raises(ValidationError):
            _AiInjectAnswer(text=text)

    assert _AiInjectAnswer(text="建议按当前方案继续，因为快照显示角色已进入目标区域。")
