"""run 规划完整详情、过往背景、知识与当前画面独立渲染，帧数据不进文本。"""

from _harness_fixtures.prompt_text import index_text, record_text

from pokemon_agent.brain import Goal
from pokemon_agent.prompt import PromptGateway, RunPlanParams
from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq
from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory
from pokemon_agent.world import Facts, TaskObservation, TaskScene


def _request() -> FromHarnessToBrainToolPlanOnceReq:
    details = [
        EpisodeMemory(
            run_id="r",
            run_goal="总目标",
            episode_id=f"e{i}",
            goal=f"局{i}",
            steps=1,
            summary=f"局{i}首句。局{i}正文第二句。",
            quality_score=0.5,
            quality_rationale="q",
            first_frame="data:image/png;base64,SECRET",
        )
        for i in range(3)
    ]
    background = RunMemory(
        run_id="past",
        run_goal="不同的总目标",
        episodes=2,
        succeeded=1,
        summary="背景首句。背景第二句不要展示。",
        quality_score=0.5,
        quality_rationale="q",
    )
    observation = TaskObservation(
        step=3,
        scene=TaskScene.WALK,
        place={"map_id": 12, "x": 3, "y": 5},
        facts=Facts(overlay="none"),
    )
    return FromHarnessToBrainToolPlanOnceReq(
        run_goal=Goal(goal="测试父目标", criteria="测试父验收条件"),
        run_id="r",
        plan=[],
        details=details,
        run_index=[background],
        knowledge=["知识甲", "知识乙"],
        observation=observation,
        max_push=1,
    )


def test_run_plan_prompt_renders_all_details_run_index_knowledge_observation() -> None:
    request = _request()

    prompt = (
        PromptGateway(None)
        .render("run_plan", RunPlanParams.model_validate(request.model_dump(mode="json")))
        .text
    )

    assert all(f"局{i}正文第二句" in prompt for i in range(3))
    assert index_text(request.run_index[0]) in prompt and "背景第二句" not in prompt
    assert "知识甲\n\n知识乙" in prompt and "地图12 x=3 y=5" in prompt
    assert "## 本层历史" in prompt
    assert "## 背景索引" in prompt
    assert "## 检索知识" in prompt and "## 当前现场" in prompt
    assert "局索引" not in prompt and "其中几局" not in prompt and "- e0:" not in prompt
    assert "data:image" not in prompt and "SECRET" not in prompt
    assert "## 附图的读法" in prompt


def test_run_history_starts_with_all_details_then_past_run_background() -> None:
    request = _request()

    blocks = PromptGateway(None).render_history(
        "run_plan", RunPlanParams.model_validate(request.model_dump(mode="json"))
    )

    assert blocks[:3] == [record_text(memory) for memory in request.details]
    assert blocks[3] == index_text(request.run_index[0])
    assert len(blocks) == 4


def test_an_empty_run_context_omits_optional_blocks_without_the_old_index_field() -> None:
    request = FromHarnessToBrainToolPlanOnceReq(
        run_goal=Goal(goal="测试父目标", criteria="测试父验收条件"),
        run_id="r",
        plan=[],
        max_push=1,
    )

    prompt = (
        PromptGateway(None)
        .render("run_plan", RunPlanParams.model_validate(request.model_dump(mode="json")))
        .text
    )

    assert "index" not in type(request).model_fields
    for title in ("本层历史", "背景索引", "检索知识", "当前现场", "状态与反馈"):
        assert f"## {title}\n" not in prompt
