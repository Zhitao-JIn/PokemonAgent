"""Every brain call records the identity of its actual text or vision handle."""

import json

import pytest
from _doubles.llm import Reply, ScriptedJudge, text_reply, vision_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.errors import AttemptFailed
from pokemon_agent.brain.interface.domain.model_call import ModelCall

LINKS = {
    "choose": "text",
    "plan": "plan",
    "decompose": "plan",
    "judge": "judge",
    "verify": "verify",
    "summarize": "verify",
    "summarize_run": "verify",
}
IDENTITIES = {
    "text": ("qwen", "qwen3.8-flash"),
    "plan": ("deepseek", "deepseek-flash"),
    "judge": ("ark", "doubao-test"),
    "verify": ("claude", "claude-haiku-5-5"),
}
REPLIES = {
    "choose": '{"action": "up"}',
    "plan": '{"new_items": [], "why": "no more goals"}',
    "decompose": '{"new_items": [], "why": "no more tasks"}',
    "judge": '{"decision": "continue", "why": "not yet"}',
    "verify": '[{"index": 0, "positive": true, "why": "observed"}]',
    "summarize": json.dumps(
        {
            "summary": "s",
            "quality_score": 0.5,
            "quality_rationale": "q",
            "markdown": "m",
            "index": {"headline": "复盘", "keys": [], "evidence": []},
        }
    ),
}
REPLIES["summarize_run"] = REPLIES["summarize"]


class IdentifiedJudge(ScriptedJudge):
    """Existing scripted provider with different public identities for each link."""

    def __init__(self, provider: str, model: str, reply: Reply) -> None:
        super().__init__(reply, multimodal=True)
        self.PROVIDER_NAME = provider
        self.model_name = model


def invoke(brain: Brain, capability: str, images: list[str]) -> list[ModelCall]:
    """Use public brain methods with the smallest complete input for each capability."""
    match capability:
        case "choose":
            result = brain.choose(prompt="p", keys=["up"], scripts=[], images=images)
        case "plan":
            result = brain.plan(
                prompt="p", goal_stack=["g"], history=["h"], max_push=1, images=images
            )
        case "decompose":
            result = brain.decompose(
                prompt="p", goal="g", context=["h"], max_tasks=1, images=images
            )
        case "judge":
            result = brain.judge(prompt="p", goal="g", history=["h"], images=images)
        case "verify":
            result = brain.verify(prompt="p", entries=["e"], goal="g", knowledge="", images=images)
        case _:
            method = brain.summarize_run if capability == "summarize_run" else brain.summarize
            result = method(
                prompt="p",
                goal="g",
                history=["h"],
                success=False,
                steps=1,
                max_steps=2,
                images=images,
                grounding_texts=[],
                termination="goal_done",
            )
    return result.calls


@pytest.mark.parametrize("capability", list(LINKS))
@pytest.mark.parametrize("outcome", ["success", "transport_failure", "parse_failure"])
@pytest.mark.parametrize("with_vision", [False, True])
@pytest.mark.parametrize("identified", [False, True])
def test_each_call_keeps_the_actual_provider_identity_even_on_failure(
    capability: str, outcome: str, with_vision: bool, identified: bool
) -> None:
    text = REPLIES[capability] if outcome == "success" else "invalid JSON"
    reply = vision_reply(text) if with_vision else text_reply(text)
    if outcome == "transport_failure":
        reply = RuntimeError("offline failure")
    providers = {
        link: IdentifiedJudge(*identity, reply)
        if identified
        else ScriptedJudge(reply, multimodal=True)
        for link, identity in IDENTITIES.items()
    }
    brain = Brain(
        decide_llm=providers["text"],
        judge_llm=providers["judge"],
        plan_llm=providers["plan"],
        summary_llm=providers["verify"],
    )
    images = ["data:image/png;base64,AAAA"] if with_vision else []

    if outcome == "success":
        calls = invoke(brain, capability, images)
        assert len(calls) == 1
        call = calls[0]
    else:
        with pytest.raises(AttemptFailed) as caught:
            invoke(brain, capability, images)
        call = caught.value.call
        assert call.payload["ok"] == "false"

    expected = IDENTITIES[LINKS[capability]] if identified else ("", "")
    assert (call.payload["provider"], call.payload["model"]) == expected
    provider = providers[LINKS[capability]]
    assert len(provider.requests) == int(not with_vision)
    assert len(provider.described) == int(with_vision)


@pytest.mark.parametrize(
    "capability", ["plan", "decompose", "verify", "summarize", "summarize_run"]
)
def test_fallback_handles_record_the_judge_provider_identity(capability: str) -> None:
    provider = IdentifiedJudge("ark", "fallback-model", text_reply(REPLIES[capability]))
    brain = Brain(judge_llm=provider)

    call = invoke(brain, capability, [])[0]

    assert (call.payload["provider"], call.payload["model"]) == ("ark", "fallback-model")
