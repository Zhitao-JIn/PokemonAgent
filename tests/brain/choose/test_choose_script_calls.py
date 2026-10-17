"""chooser 解析：`Brain._parse` 解析脚本动作名与 args，以及经公共 `BrainPort.choose`。"""

from __future__ import annotations

import pytest

from pokemon_agent.brain.brain import Brain
from pokemon_agent.brain.errors import IllegalAction, ParseFailure
from pokemon_agent.brain.interface import ScriptArg, ScriptSignature

# ---- 3. chooser 解析：脚本名 + args ----

_SCRIPT_SIGS = [
    ScriptSignature(
        name="walk_to",
        params=[
            ScriptArg(name="x", type="int", required=True),
            ScriptArg(name="y", type="int", required=True),
        ],
    )
]


def _brain() -> Brain:
    return Brain.__new__(Brain)  # _parse 不碰 provider，绕过 __init__


def test_parse_script_action_with_args() -> None:
    action = _brain()._parse(
        '{"action": "walk_to", "args": {"x": 5, "y": 2}}', ["a", "up"], _SCRIPT_SIGS
    )
    assert action.script is not None and action.script.name == "walk_to"
    assert action.script.args == {"x": 5, "y": 2}
    assert action.describe() == "script:walk_to(x=5, y=2)"


def test_choose_accepts_flat_script_parameters_through_the_public_brain_port() -> None:
    from pokemon_agent.brain.schemas import LlmCompleteReq, LlmCompleteResp

    class FlatScriptProvider:
        """固定回答的文本 provider，不调用外部模型。"""

        def complete(self, request: LlmCompleteReq) -> LlmCompleteResp:
            return LlmCompleteResp(text='{"action": "walk_to", "x": 5, "y": 2}')

    brain = Brain(decide_llm=FlatScriptProvider())

    result = brain.choose(prompt="选择一条允许的脚本", keys=[], scripts=_SCRIPT_SIGS)

    assert result.action.script is not None
    assert result.action.script.name == "walk_to"
    assert result.action.script.args == {"x": 5, "y": 2}
    assert len(result.calls) == 1


def test_parse_script_missing_required_arg_is_parse_failure() -> None:
    with pytest.raises(ParseFailure):
        _brain()._parse('{"action": "walk_to", "args": {"x": 5}}', ["a", "up"], _SCRIPT_SIGS)


def test_parse_unknown_name_lists_scripts_in_illegal() -> None:
    with pytest.raises(IllegalAction) as exc:
        _brain()._parse('{"action": "nope"}', ["a", "up"], _SCRIPT_SIGS)
    assert "walk_to" in exc.value.allowed  # 脚本名在"当时允许"清单里


def test_parse_still_prefers_keys_over_scripts() -> None:
    action = _brain()._parse('{"action": "up"}', ["a", "up"], _SCRIPT_SIGS)
    assert action.sequence and action.script is None
