"""真实能力经离线 provider 重试，成功与耗尽都保留版本戳。"""

import pytest
from _doubles.llm import ScriptedJudge, text_reply
from _harness_fixtures.app_config import call_policy

from pokemon_agent.brain import Brain
from pokemon_agent.direct.brain_tool import Verifier
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.prompt import PromptGateway, VerifyParams
from pokemon_agent.schemas.harness import FromHarnessToBrainToolVerifyReq

from .golden_cases import active_version


@pytest.mark.parametrize("exhausted", [False, True])
def test_real_verify_capability_stamps_failed_and_successful_attempts(exhausted: bool) -> None:
    replies = [text_reply("invalid"), text_reply("invalid" if exhausted else '{"verdicts": []}')]
    provider = ScriptedJudge(*replies)
    gateway = PromptGateway(None)
    verifier = Verifier(
        Brain(summary_llm=provider), policy=call_policy(max_attempts=2), prompt_gateway=gateway
    )
    req = FromHarnessToBrainToolVerifyReq(entries=[], goal="确认")
    rendered = gateway.render("verify", VerifyParams(goal=req.goal, entries=[]))

    if exhausted:
        with pytest.raises(MaxRetriesExceeded) as caught:
            verifier.verify(req)
        calls = caught.value.calls
    else:
        calls = verifier.verify(req).calls

    assert len(calls) == len(provider.requests) == 2
    for call in calls:
        assert call.payload["prompt_task"] == "verify"
        assert call.payload["prompt_version"] == active_version("verify")
        assert call.payload["prompt_hash"] == rendered.hash
        assert call.payload["prompt"] == rendered.text
    assert calls[0].error_kind == "ParseFailure"
    assert bool(calls[-1].error_kind) == exhausted
