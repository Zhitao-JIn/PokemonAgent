"""run 蒸馏复用 provider，并保持一次尝试与 run 方言。"""

import pytest
from _doubles.llm import ScriptedJudge, text_reply, vision_reply
from _harness_fixtures.app_config import call_policy

from pokemon_agent.brain import Brain, RunSummary, Task
from pokemon_agent.brain.errors import SummarizeAttemptFailed
from pokemon_agent.direct.brain_tool import RunSummarizer
from pokemon_agent.schemas.harness import FromHarnessToBrainToolSummarizeRunReq
from pokemon_agent.schemas.harness.domain import EntryStatus, GoalEntry, Termination
from pokemon_agent.schemas.memory import EpisodeMemory


def test_run_summary_uses_the_summary_provider_once_and_returns_its_own_dialect() -> None:
    summary = RunSummary(summary="复盘", quality_score=0.5, quality_rationale="q", markdown="全文")
    provider = ScriptedJudge(text_reply(summary.model_dump_json()))
    brain = Brain(verify_llm=provider)

    result = brain.summarize_run(
        prompt="规则和素材", goal="g", history=["h"], success=False, steps=1, max_steps=2
    )

    assert isinstance(result.summary, RunSummary)
    assert result.summary == summary
    assert len(result.calls) == len(provider.requests) == 1
    assert provider.requests[0].prompt == "规则和素材"
    assert result.calls[0].payload["images"] == []


def test_run_summary_parse_failure_is_one_failed_attempt_without_internal_retry() -> None:
    provider = ScriptedJudge(text_reply("invalid"))
    brain = Brain(verify_llm=provider)

    with pytest.raises(SummarizeAttemptFailed) as caught:
        brain.summarize_run(
            prompt="p", goal="g", history=["h"], success=False, steps=1, max_steps=2
        )

    assert len(provider.requests) == 1
    assert caught.value.call.error_kind == "ParseFailure"


def test_run_summary_prompt_keeps_final_overturns_and_complete_episode_text_without_frames() -> (
    None
):
    summary = RunSummary(summary="复盘", quality_score=0.5, quality_rationale="q", markdown="全文")
    provider = ScriptedJudge(vision_reply(summary.model_dump_json()), multimodal=True)
    task = Task(task_id="g1", goal="局目标", success_criteria="c", max_steps=2)
    memory = EpisodeMemory(
        run_id="r1",
        run_goal="总目标",
        episode_id="e1",
        goal="局目标",
        termination="goal_done",
        steps=1,
        summary="第一句。第二句完整保留。",
        quality_score=0.5,
        quality_rationale="q",
        first_frame="data:image/png;base64,SECRET",
    )
    req = FromHarnessToBrainToolSummarizeRunReq(
        run_id="r1",
        run_goal="总目标",
        goals=[GoalEntry(task=task, status=EntryStatus.FAILED, note="人工判失败", overturned=True)],
        episode_memories=[memory],
        termination=Termination.STALLED,
        judge_reason="停摆",
        episodes=1,
        succeeded=1,
        acts_used=2,
        max_episodes=3,
    )

    result = RunSummarizer(Brain(verify_llm=provider), policy=call_policy()).summarize_run(req)
    prompt = provider.described[0].prompt

    assert "总目标" in prompt and "人工判失败" in prompt and "overturned=true" in prompt
    assert "第二句完整保留" in prompt
    assert "data:image" not in prompt and "SECRET" not in prompt
    assert not result.run_memory.success
    assert result.run_memory.succeeded == 1
