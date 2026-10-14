"""`Brain.choose` 的转发表：有图且模型多模态才走 `describe`，否则退化纯文本。

守的是「转发表在 brain 这一层」——入参带图、且 decide provider 的 `multimodal`
为真才走 `describe()`；两者缺一退化成 `complete()`。账上的 `images` 反映「真发给
模型的图」（发了什么存什么）。
"""

from __future__ import annotations

from _doubles.brain_choose import IMAGE, KEYS, PROMPT, SCRIPTS
from _doubles.llm import ScriptedJudge, ScriptedLLM, text_reply, vision_reply

from pokemon_agent.brain import Brain
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq


def test_images_go_through_describe_when_the_model_is_multimodal() -> None:
    provider = ScriptedJudge(vision_reply('{"action": "up"}'), multimodal=True)
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS, images=[IMAGE, IMAGE])

    assert provider.described == [VisionDescribeReq(images=[IMAGE, IMAGE], prompt=PROMPT)]
    assert provider.requests == []
    assert result.calls[0].payload["images"] == [IMAGE, IMAGE]


def test_images_are_dropped_to_plain_text_when_the_model_is_not_multimodal() -> None:
    provider = ScriptedJudge(text_reply('{"action": "up"}'), multimodal=False)
    brain = Brain(decide_llm=provider)

    result = brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS, images=[IMAGE])

    assert provider.requests == [LlmCompleteReq(prompt=PROMPT)]
    assert provider.described == []
    assert result.calls[0].payload["images"] == []


def test_no_images_means_plain_completion_even_for_a_multimodal_model() -> None:
    provider = ScriptedJudge(text_reply('{"action": "up"}'), multimodal=True)
    brain = Brain(decide_llm=provider)

    brain.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS)

    assert len(provider.requests) == 1
    assert provider.described == []


def test_the_two_response_shapes_land_in_the_same_ledger_keys() -> None:
    vision = Brain(decide_llm=ScriptedJudge(vision_reply('{"action": "up"}'), multimodal=True))
    text = Brain(decide_llm=ScriptedLLM(text_reply('{"action": "up"}')))

    vision_payload = (
        vision.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS, images=[IMAGE]).calls[0].payload
    )
    text_payload = text.choose(prompt=PROMPT, keys=KEYS, scripts=SCRIPTS).calls[0].payload

    assert set(vision_payload) == set(text_payload)
    assert vision_payload["input_tokens"] == "21"
    assert vision_payload["output_tokens"] == "9"
    assert vision_payload["cached_tokens"] == "4"
    assert vision_payload["reasoning_tokens"] == "5"
    assert text_payload["input_tokens"] == "11"
    assert text_payload["output_tokens"] == "7"
    assert text_payload["cached_tokens"] == "3"
    assert text_payload["reasoning_tokens"] == "2"
