"""Model identity survives BrainTool translation and disk trace round trips."""

import json
from pathlib import Path

import pytest
from _doubles.llm import ScriptedLLM, text_reply
from _harness_fixtures.app_config import ACTION_LIMITS, call_policy

from pokemon_agent.brain import Brain
from pokemon_agent.brain.interface import Goal
from pokemon_agent.direct.brain_tool import Chooser
from pokemon_agent.direct.trace import TraceTool, parse
from pokemon_agent.direct.trace.content import ModelCallContent
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.world import ActionSpace, TaskObservation, TaskScene


class RecordedLLM(ScriptedLLM):
    """A scripted text model with the same public identity fields as providers."""

    PROVIDER_NAME = "qwen"
    model_name = "qwen3.8-flash"


@pytest.mark.parametrize("identity", [{}, {"provider": "qwen", "model": "qwen3.8-flash"}])
def test_model_call_content_reads_both_old_and_recorded_identity(identity: dict[str, str]) -> None:
    content = ModelCallContent.model_validate({"input_tokens": "11", **identity})

    assert content.input_tokens == 11
    assert content.provider == identity.get("provider", "")
    assert content.model == identity.get("model", "")


def test_brain_identity_survives_tool_translation_and_disk_round_trip(tmp_path: Path) -> None:
    provider = RecordedLLM(text_reply('{"action": "up"}'))
    chooser = Chooser(
        Brain(decide_llm=provider),
        policy=call_policy(),
        action_limits=ACTION_LIMITS,
        prompt_gateway=PromptGateway(None),
    )
    trace = TraceTool.build(run_id="r1", trace_root=tmp_path)

    response = chooser.choose(
        FromHarnessToBrainToolChooseOnceReq(
            goals=[Goal(goal="g", criteria="c")],
            obs=TaskObservation(facts={"overlay": "none"}, step=0, scene=TaskScene.WALK),
            space=ActionSpace(names=["up"], descriptions={"up": "north"}),
            memories=[],
        )
    )
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHOOSE_CALL,
            calls=response.calls,
            meta={"source": "plan_task", "episode_id": "e1", "task_id": "t1", "step": 1},
        )
    )
    raw = trace.read_events()[0]
    persisted = json.loads(raw.content)
    content = parse(raw).content

    assert response.calls[0].payload["provider"] == persisted["provider"] == "qwen"
    assert response.calls[0].payload["model"] == persisted["model"] == "qwen3.8-flash"
    assert isinstance(content, ModelCallContent)
    assert (content.provider, content.model) == ("qwen", "qwen3.8-flash")
