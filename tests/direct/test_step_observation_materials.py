"""逐键观察经真实门面转成提示词素材，统一用于选择、判定、校验和摘要。"""

from _harness_fixtures.app_config import DEFAULT_APP_CONFIG
from _harness_fixtures.brain import _Brain

from pokemon_agent.brain import Goal
from pokemon_agent.direct.brain_tool import (
    Judger,
    TaskSummarizer,
    Verifier,
    decide_prompt_params,
)
from pokemon_agent.direct.call_policy import CallPolicy
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolSummarizeTaskReq,
    FromHarnessToBrainToolVerifyReq,
)
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import ActionSpace, TaskObservation, TaskScene


def memory() -> ActMemory:
    place = {"map_id": 1, "x": 2, "y": 3}
    ram = {"in_battle": False, "money": 100, "bag": [], "party": []}
    before = {"step": 0, "place": place, "scene": "walk", "facts": {"overlay": "none"}, "ram": ram}
    observations = [
        {
            "step": 1,
            "place": place,
            "facing": "north",
            "scene": "walk",
            "overlay": "none",
            "dialog_text": "ALPHA",
            "ram": ram,
        },
        {
            "step": 2,
            "place": place,
            "facing": "north",
            "scene": "walk",
            "overlay": "none",
            "dialog_text": "BETA",
            "ram": ram,
        },
        {
            "step": 3,
            "place": place,
            "facing": "north",
            "scene": "walk",
            "overlay": "none",
            "dialog_text": "ALPHA",
            "ram": ram,
        },
    ]
    return ActMemory.model_validate(
        {
            "before": before,
            "after": before,
            "step": 0,
            "episode_id": "ep",
            "task_id": "t",
            "action": "script:advance_dialog()",
            "observations": observations,
            "outcome": {"ok": True, "code": "ok", "summary": "完成对话"},
        }
    )


def test_chooser_receives_structured_outcome_and_all_changes_in_prompt() -> None:
    entry = memory()
    obs = TaskObservation(step=1, scene=TaskScene.WALK, facts={"overlay": "none"})
    request = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="g", criteria="c")],
        obs=obs,
        space=ActionSpace(names=["a"]),
        memories=[entry],
        last_outcome=entry.outcome,
    )

    params = decide_prompt_params(request, max_segments=1)
    text = PromptGateway(None).render("decide_action", params).text

    assert [change.text for change in params.memories[0].changes] == ["ALPHA", "BETA", "ALPHA"]
    assert params.last_changes == params.memories[0].changes
    assert "observations" not in params.memories[0].model_dump()
    assert "上一个脚本的结局" in text and "完成对话" in text
    assert "上一个脚本的观察变化" in text and "BETA" in text
    assert text.count("ALPHA") >= 2


def test_judge_verify_and_task_summary_receive_the_same_evidence() -> None:
    entry = memory()
    brain = _Brain(lambda _: False, lambda _: False, lambda _: False, 1)
    policy = CallPolicy(retry=DEFAULT_APP_CONFIG.retry, request_timeout_s=30, image_cap=4)
    gateway = PromptGateway(None)
    judge = Judger(brain, policy=policy, prompt_gateway=gateway)
    verify = Verifier(brain, policy=policy, prompt_gateway=gateway)
    summary = TaskSummarizer(brain, policy=policy, prompt_gateway=gateway)

    judged = judge.judge(
        FromHarnessToBrainToolJudgeReq(goal=Goal(goal="g", criteria="c"), history=[entry])
    )
    verified = verify.verify(FromHarnessToBrainToolVerifyReq(goal="g", entries=[entry]))
    summarized = summary.summarize_task(
        FromHarnessToBrainToolSummarizeTaskReq(
            entries=[entry],
            verdicts=[],
            entry_id="e",
            task_id="t",
            episode_id="ep",
            run_id="r",
            goal="g",
            termination="goal_done",
            steps_used=1,
            max_steps=3,
        )
    )

    for result in (judged, verified, summarized):
        prompt = result.calls[0].payload["prompt"]
        assert "ALPHA" in prompt and "BETA" in prompt and "完成对话" in prompt


def test_long_script_observations_are_not_truncated_in_memory_material() -> None:
    entry = memory()
    template = entry.observations[0].model_dump(mode="json")
    observations = [
        ActMemory.Observation.StepObs.model_validate(
            {**template, "step": step, "dialog_text": f"LINE {step:03d}"}
        )
        for step in range(1, 201)
    ]
    entry = entry.model_copy(update={"observations": observations})
    obs = TaskObservation(step=1, scene=TaskScene.WALK, facts={"overlay": "none"})
    request = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal="g", criteria="c")],
        obs=obs,
        space=ActionSpace(names=["a"]),
        memories=[entry],
        last_outcome=entry.outcome,
    )

    params = decide_prompt_params(request, max_segments=1)
    text = PromptGateway(None).render("decide_action", params).text

    assert len(params.memories[0].changes) == 200
    assert len(params.last_changes) == 200
    assert "LINE 001" in text and "LINE 200" in text
