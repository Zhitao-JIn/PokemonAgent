"""摘要索引只引用逐层材料，失败进入现有重试。"""

import json

import pytest
from _doubles.llm import ScriptedJudge, text_reply
from _harness_fixtures.app_config import call_policy

from pokemon_agent.brain import Brain
from pokemon_agent.direct.brain_tool import RunSummarizer, Summarizer, TaskSummarizer
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeTaskReq,
)
from tests.prompt.distillation_examples import examples


def reply(key: str, *, headline: str = "探索", evidence: str = "对话原文") -> str:
    return json.dumps(
        {
            "summary": "经过",
            "reason": "原因",
            "quality_score": 0.5,
            "quality_rationale": "依据",
            "index": {
                "headline": headline,
                "keys": [key],
                "evidence": [evidence],
            },
        },
        ensure_ascii=False,
    )


@pytest.mark.parametrize("layer", ["summarize_task", "summarize", "summarize_run"])
def test_summary_checks_each_layer_grounding_and_retries(layer: str) -> None:
    data = examples()[layer].model_dump(mode="json")
    data.update(run_id="r", episode_id="e", entry_id="entry", run_goal="总目标")
    if layer == "summarize_task":
        for entry in data["entries"]:
            entry["before_frame"] = entry["after_frame"] = None
            entry["before"]["facts"]["screen"] = "仅在屏幕的关键字"
        data["termination"] = "goal_done"
        request = FromHarnessToBrainToolSummarizeTaskReq.model_validate(data)
        kind, accepted = TaskSummarizer, "屏幕的关键字"
    elif layer == "summarize":
        for entry in data["entries"]:
            entry["first_frame"] = entry["last_frame"] = None
            entry["index"] = {"headline": "下层", "keys": ["任务索引词"], "evidence": []}
        request = FromHarnessToBrainToolSummarizeReq.model_validate(data)
        kind, accepted = Summarizer, "任务索引词"
    else:
        for entry in data["episode_memories"]:
            entry["first_frame"] = entry["last_frame"] = None
            entry["index"] = {"headline": "下层", "keys": ["局索引词"], "evidence": []}
        request = FromHarnessToBrainToolSummarizeRunReq.model_validate(data)
        kind, accepted = RunSummarizer, "局索引词"
    provider = ScriptedJudge(text_reply(reply("虚构词")), text_reply(reply(accepted)))
    tool = kind(
        Brain(summary_llm=provider), policy=call_policy(), prompt_gateway=PromptGateway(None)
    )

    result = getattr(tool, layer)(request)

    assert len(provider.requests) == len(result.calls) == 2
    assert result.summary.index.keys == [accepted]
    memory = getattr(
        result,
        {"summarize_task": "memory", "summarize": "episode_memory", "summarize_run": "run_memory"}[
            layer
        ],
    )
    if layer == "summarize_task":
        assert memory.pointers == [f"{request.entries[0].step}-{request.entries[-1].after.step}"]
    elif layer == "summarize":
        assert memory.pointers == [item.task_id for item in request.entries]
    else:
        assert memory.pointers == [item.episode_id for item in request.episode_memories]
    assert ("facts" in type(memory).model_fields) == (layer == "summarize_task")


@pytest.mark.parametrize(
    "bad",
    [
        {"headline": "失败", "evidence": "对话原文"},
        {"headline": "探索", "evidence": "臆测"},
    ],
)
def test_invalid_headline_or_evidence_uses_existing_retry(bad: dict[str, str]) -> None:
    data = examples()["summarize_task"].model_dump(mode="json")
    data.update(run_id="r", episode_id="e", entry_id="entry", termination="goal_done")
    for entry in data["entries"]:
        entry["before_frame"] = entry["after_frame"] = None
        entry["before"]["facts"]["screen"] = "标牌"
    request = FromHarnessToBrainToolSummarizeTaskReq.model_validate(data)
    provider = ScriptedJudge(text_reply(reply("标牌", **bad)), text_reply(reply("标牌")))
    tool = TaskSummarizer(
        Brain(summary_llm=provider), policy=call_policy(), prompt_gateway=PromptGateway(None)
    )

    result = tool.summarize_task(request)

    assert len(result.calls) == 2
    assert result.calls[0].error_kind == "ParseFailure"


@pytest.mark.parametrize(
    "termination,headline",
    [
        ("goal_done", "失败"),
        ("goal_done", "未达成"),
        ("goal_done", "未完成"),
        ("goal_done", "没做成"),
        ("stalled", "成功"),
        ("stalled", "达成"),
    ],
)
def test_every_forbidden_outcome_word_retries(termination: str, headline: str) -> None:
    data = examples()["summarize_task"].model_dump(mode="json")
    data.update(run_id="r", episode_id="e", entry_id="entry", termination=termination)
    for entry in data["entries"]:
        entry["before_frame"] = entry["after_frame"] = None
        entry["before"]["facts"]["screen"] = "标牌"
    request = FromHarnessToBrainToolSummarizeTaskReq.model_validate(data)
    provider = ScriptedJudge(
        text_reply(reply("标牌", headline=headline)), text_reply(reply("标牌"))
    )
    tool = TaskSummarizer(
        Brain(summary_llm=provider), policy=call_policy(), prompt_gateway=PromptGateway(None)
    )

    result = tool.summarize_task(request)

    assert len(result.calls) == 2
    assert result.calls[0].error_kind == "ParseFailure"
