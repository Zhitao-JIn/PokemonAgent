"""三层共用内存观测：取帧、场景检索、序列化与记忆过滤的用法示范。"""

from pathlib import Path

import pytest
from _harness_fixtures.harness import build_fake
from _harness_fixtures.prompt_text import observation_text
from _harness_fixtures.world import _Game
from langgraph.runtime import Runtime

from pokemon_agent.brain import Action, ActionSegment, Goal, Task
from pokemon_agent.direct.trace import parse
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.episode.perceive.retrieve_knowledge_semantic_memory import (
    retrieve_knowledge_semantic_memory,
)
from pokemon_agent.harness.episode.perceive.sense import sense as episode_sense
from pokemon_agent.harness.run.perceive.sense import sense as run_sense
from pokemon_agent.harness.run.run_state import RunState
from pokemon_agent.prompt import DecomposeParams, PromptGateway
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolReflectReq,
    FromHarnessToGameToolPerceiveTaskResp,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EpisodeOutput, Termination
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import TERRAIN_MEANING, Facts, Observation, TaskObservation, TaskScene
from pokemon_agent.world.interface.domain.takeover_view import NamingView


def observation(scene: TaskScene = TaskScene.NAMING) -> TaskObservation:
    """带确定文字和位置的内存观测，起名场合另带业务视图。"""
    return TaskObservation(
        step=0,
        scene=scene,
        takeover=NamingView(target="YOUR NAME?", typed="RED")
        if scene is TaskScene.NAMING
        else None,
        place={"map_id": 12, "x": 3, "y": 5},
        facts=Facts(overlay="none", facing="south", screen="YOUR NAME?"),
    )


class ObservationGame(_Game):
    """沿用完整 GameToolPort 假件，只把内存帧固定为本测试的观测。"""

    def __init__(self) -> None:
        super().__init__(fail_on_press=None)

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        return FromHarnessToGameToolPerceiveTaskResp(
            observation=observation(), frame_png="data:image/png;base64,cG5n"
        )


def run_state(obs: TaskObservation | None = None) -> RunState:
    """本轮之前已派两局、累计十七个动作的 run 状态。"""
    return RunState(
        run_id="r1",
        run_goal=Goal(goal="到达目标", criteria="坐标正确"),
        goals=[],
        step=2,
        total_acts=17,
        observation=obs,
    )


def episode_state(obs: TaskObservation | None = None) -> EpisodeRunState:
    """与 run 使用相同圈号、动作数的 episode 状态。"""
    return EpisodeRunState(
        run_id="r1",
        run_goal="测试总目标",
        episode_id="r1-ep1",
        step=2,
        total_acts=17,
        goal=Task(task_id="g1", goal="到达目标", success_criteria="坐标正确", max_steps=6),
        ep_ctx=EpisodeContext(observation=obs),
    )


@pytest.mark.parametrize("level", ["run", "episode"])
def test_sense_uses_memory_observation_and_preserves_both_step_numbers(
    tmp_path: Path, level: str
) -> None:
    fake = build_fake(tmp_path)
    game = ObservationGame()
    fake.run_rt.game = game
    fake.run_rt.episode.game = game

    if level == "run":
        update = run_sense(run_state(), Runtime(context=fake.run_rt))
        obs = update["observation"]
    else:
        update = episode_sense(episode_state(), Runtime(context=fake.run_rt.episode))
        obs = update["ep_ctx"].observation

    assert isinstance(obs, TaskObservation)
    assert obs.scene is TaskScene.NAMING and obs.takeover is not None
    assert obs.step == 17
    events = [parse(e) for e in fake.trace.read_events()]
    assert [e.kind for e in events] == [TraceKind.SENSE_FRAME]
    assert events[0].meta.step == 3
    assert events[0].content.scene is TaskScene.NAMING
    assert events[0].content.takeover == obs.takeover


@pytest.mark.parametrize("snapshot", [False, True])
def test_current_and_legacy_memory_render_without_blind_note(snapshot: bool) -> None:
    obs = observation()
    stored = ActMemory.Observation.model_validate(
        {**obs.model_dump(mode="json"), "perceived": False}
    )

    text = observation_text(stored) if snapshot else observation_text(obs)

    assert "没做视觉感知" not in text
    assert "地图12 x=3 y=5" in text
    assert "perceived" not in obs.model_dump()
    assert text == observation_text(obs)


def test_knowledge_refresh_uses_task_scene_when_facts_scene_does_not_change(
    tmp_path: Path,
) -> None:
    fake = build_fake(tmp_path)
    state = episode_state(observation(TaskScene.WALK))
    runtime = Runtime(context=fake.run_rt.episode)
    state = state.model_copy(update=retrieve_knowledge_semantic_memory(state, runtime))
    assert retrieve_knowledge_semantic_memory(state, runtime) == {}
    next_obs = observation(TaskScene.SHOP)
    assert next_obs.facts.scene == state.ep_ctx.observation.facts.scene
    state = state.model_copy(
        update={"ep_ctx": state.ep_ctx.model_copy(update={"observation": next_obs})}
    )

    result = retrieve_knowledge_semantic_memory(state, runtime)

    assert "ep_ctx" in result
    assert result["ep_ctx"].knowledge_scene == "shop"
    events = [parse(e) for e in fake.trace.read_events()]
    assert [e.kind for e in events] == [TraceKind.READ_KNOWLEDGE] * 2
    assert "scene:walk" in events[0].content.query
    assert "scene:shop" in events[1].content.query


@pytest.mark.parametrize("carrier", ["run", "episode", "output", "decompose", "trace"])
def test_scene_and_takeover_survive_json_round_trip(carrier: str) -> None:
    obs = observation()
    if carrier == "run":
        value = run_state(obs)
        restored = RunState.model_validate_json(value.model_dump_json()).observation
    elif carrier == "episode":
        value = episode_state(obs)
        restored = EpisodeRunState.model_validate_json(value.model_dump_json()).ep_ctx.observation
    elif carrier == "output":
        value = EpisodeOutput(
            episode_id="r1-ep1",
            goal_id="g1",
            termination=Termination.GOAL_DONE,
            tasks_used=1,
            acts_used=1,
            observation=obs,
        )
        restored = EpisodeOutput.model_validate_json(value.model_dump_json()).observation
    elif carrier == "decompose":
        value = FromHarnessToBrainToolDecomposeReq(
            goal=Goal(goal="g", criteria="c"),
            observation=obs,
            max_tasks=2,
        )
        restored = FromHarnessToBrainToolDecomposeReq.model_validate_json(
            value.model_dump_json()
        ).observation
    else:
        value = FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={},
            obs=obs,
        )
        restored = FromHarnessToTraceToolAppendReq.model_validate_json(value.model_dump_json()).obs

    assert isinstance(restored, TaskObservation)
    assert restored.scene is obs.scene
    assert restored.takeover == obs.takeover


def test_legacy_trace_observation_without_task_scene_still_loads() -> None:
    req = FromHarnessToTraceToolAppendReq.model_validate(
        {"kind": "sense_frame", "meta": {}, "obs": {"step": 0, "status": "旧帧"}}
    )

    assert isinstance(req.obs, Observation)
    assert not isinstance(req.obs, TaskObservation)


def test_task_observation_is_written_as_memory_with_retrieval_fields_filtered(
    tmp_path: Path,
) -> None:
    fake = build_fake(tmp_path)
    obs = observation()
    obs.facts.knowledge = "临时知识检索结果"
    req = FromHarnessToBrainToolReflectReq(
        before=obs,
        after=obs,
        action=Action(sequence=[ActionSegment(name="a")]),
        episode_id="r1-ep1",
        step=1,
    )

    entry = fake.run_rt.episode.task.reflector.reflect(req).entry

    for stored in (entry.before, entry.after):
        assert stored.scene == "naming"
        assert "knowledge" not in stored.facts.model_dump()
    assert obs.facts.knowledge == "临时知识检索结果"


def test_episode_prompt_keeps_existing_sections_after_memory_sense(tmp_path: Path) -> None:
    fake = build_fake(tmp_path)
    fake.run_rt.episode.game = ObservationGame()
    update = episode_sense(episode_state(), Runtime(context=fake.run_rt.episode))
    obs = update["ep_ctx"].observation
    req = FromHarnessToBrainToolDecomposeReq(
        goal=Goal(goal="填写名字", criteria="名字为 RED"),
        observation=obs,
        max_tasks=2,
    )

    prompt = build_prompt(req)
    legacy_obs = Observation.model_validate(obs.model_dump())
    legacy_prompt = build_prompt(req.model_copy(update={"observation": legacy_obs}))

    # 步骤 1：task_frame 展示起名视图，旧输入缺字段，等式守卫不再成立（CHANGELOG 647）。
    assert "None" not in prompt and "没做视觉感知" not in prompt
    assert "None" not in legacy_prompt and "没做视觉感知" not in legacy_prompt
    current_frame = prompt.split("\n## 当前现场\n", 1)[1].split("\n## ", 1)[0]
    assert "起名：YOUR NAME?" in current_frame
    assert "已输入：RED" in current_frame
    for rendered in (prompt, legacy_prompt):
        input_section = rendered.split("\n## 本次输入\n", 1)[1]
        assert "\n## 当前现场\n" in input_section
        assert "\n## 检索知识\n" not in rendered
    (tmp_path / "sense_prompt.txt").write_text(prompt, encoding="utf-8")


def build_prompt(req: FromHarnessToBrainToolDecomposeReq) -> str:
    """Render the same decomposition materials through the gateway."""
    params = DecomposeParams.model_validate(
        {
            **req.model_dump(mode="json", exclude={"observation"}),
            "observation": req.observation.model_dump(mode="json"),
            "terrain_meanings": TERRAIN_MEANING,
        }
    )
    return PromptGateway(None).render("decompose", params).text
