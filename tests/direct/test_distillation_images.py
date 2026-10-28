"""三层蒸馏经真实 tool/Brain 到假 provider 的图像顺序与旧版相同。"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from _doubles.llm import ScriptedJudge, vision_reply
from _harness_fixtures.app_config import call_policy

from pokemon_agent.brain import Brain
from pokemon_agent.direct.brain_tool import RunSummarizer, Summarizer, TaskSummarizer
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeTaskReq,
)
from tests.prompt.distillation_examples import examples, old_gateway


@pytest.mark.parametrize("task", ["summarize_task", "summarize", "summarize_run"])
def test_provider_gets_the_same_ordered_frames_and_caps_in_both_versions(
    task: str, tmp_path: Path
) -> None:
    contracts = {
        "summarize_task": FromHarnessToBrainToolSummarizeTaskReq,
        "summarize": FromHarnessToBrainToolSummarizeReq,
        "summarize_run": FromHarnessToBrainToolSummarizeRunReq,
    }
    capabilities = {
        "summarize_task": TaskSummarizer,
        "summarize": Summarizer,
        "summarize_run": RunSummarizer,
    }
    data = examples()[task].model_dump(mode="json")
    empty_index = {"headline": "", "keys": [], "evidence": []}
    if task == "summarize_task":
        for entry in data["entries"]:
            entry.update(observations=[], outcome=None)
    elif task == "summarize":
        for entry in data["entries"]:
            entry.update(facts=[], pointers=[], index=empty_index.copy())
    else:
        for entry in data["episode_memories"]:
            entry.update(pointers=[], index=empty_index.copy())
    request = contracts[task].model_validate(
        {
            **data,
            "run_id": "r",
            "episode_id": "e",
            "entry_id": "entry",
            "run_goal": "读取招牌",
        }
    )
    reply = json.dumps(
        {
            "index": {"headline": "探索", "keys": [], "evidence": []},
            "summary": "完整蒸馏正文",
            "reason": "完整结论",
            "quality_score": 0.5,
            "quality_rationale": "样本有限",
            "markdown": "完整 Markdown 正文",
        }
    )
    policy = replace(call_policy(), image_cap=2)
    frames: list[list[str]] = []

    for gateway in (old_gateway(tmp_path), PromptGateway(None)):
        provider = ScriptedJudge(vision_reply(reply))
        tool = capabilities[task](
            Brain(summary_llm=provider), policy=policy, prompt_gateway=gateway
        )
        result = getattr(tool, task)(request)
        assert len(provider.described) == 1
        frames.append(provider.described[0].images)
        assert result.calls[0].payload["images"] == frames[-1]
        assert result.summary.summary == "完整蒸馏正文"

    assert frames[0] == frames[1] == (["B", "C"] if task == "summarize_run" else ["A", "B", "C"])
