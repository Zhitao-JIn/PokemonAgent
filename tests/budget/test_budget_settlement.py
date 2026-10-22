"""真正三层图在预算耗尽后机械收尾；假模型与假世界不访问网络。"""

import json

import pytest
from _doubles.llm import ScriptedLLM, text_reply
from _fake_run import GOAL, build_fake, every, never
from _harness_fixtures.app_config import call_policy, reconfigure

from pokemon_agent.brain import Brain, Goal
from pokemon_agent.deadline import Deadline
from pokemon_agent.direct.brain_tool import Decomposer
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.harness.checkpoint.manifest import state_schema_hash
from pokemon_agent.harness.episode.episode_state import EpisodeContext, EpisodeRunState
from pokemon_agent.harness.run import compile_run_graph
from pokemon_agent.harness.run.run_state import RunState
from pokemon_agent.harness.task.task_entry import begin_task
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolDecomposeReq, TraceKind
from pokemon_agent.schemas.harness.domain import GoalEntry, TaskInput, Termination
from pokemon_agent.world import TaskObservation, TaskScene


class Clock:
    """单调假时钟；不等待真实时间。"""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def configure(fake, **overrides):
    return reconfigure(fake.run_rt, budget=overrides).budget


def events(fake):
    return fake.trace.read_events({"run_id": "r1"})


def assert_mechanical_tail(fake):
    stream = events(fake)
    first_stop = next(i for i, event in enumerate(stream) if event.kind == "budget_skipped")
    assert not [
        event
        for event in stream[first_stop:]
        if event.type == "model_call" and event.kind != "summarize_run_call"
    ]
    assert sum(event.kind == "run_end" for event in stream) == 1
    assert not [event for event in stream if event.kind.endswith("_error")]


def test_slow_decomposition_leaves_time_for_mechanical_run_end(tmp_path):
    fake = build_fake(tmp_path)
    clock = Clock()
    budget = configure(fake, wall_clock_s=100.0)
    deadline = Deadline(100, budget.reserve_s, budget.min_request_s, clock=clock)

    class SlowProvider(ScriptedLLM):
        def complete(self, req):
            clock.now += 45
            return super().complete(req)

    provider = SlowProvider(
        text_reply('{"tasks":[{"goal":"子任务","success_criteria":"c","max_steps":2}]}')
    )
    fake.run_rt.episode.decomposer = Decomposer(
        Brain(plan_llm=provider),
        policy=call_policy(),
        deadline=deadline,
        prompt_gateway=PromptGateway(None),
    )
    for deps in (fake.run_rt, fake.run_rt.episode, fake.run_rt.episode.task):
        deps.deadline = deadline

    result = fake.harness.run("r1", [GOAL])

    assert result.termination == Termination.TIME_EXHAUSTED.value
    assert len(provider.requests) == 1 and clock.now == 45
    assert result.outcomes[0].tasks_used == 0
    assert_mechanical_tail(fake)


def test_action_budget_accumulates_across_successful_episodes(tmp_path):
    fake = build_fake(tmp_path, task=every(1), episode=every(1), run=never)
    configure(fake, max_total_actions=3)

    result = fake.harness.run("r1", [GOAL])

    assert result.termination == Termination.ACTIONS_EXHAUSTED.value
    assert sum(outcome.acts_used for outcome in result.outcomes) == 3
    assert result.outcomes[0].success and result.outcomes[1].success
    assert_mechanical_tail(fake)


@pytest.mark.parametrize(
    "limit, expected",
    [
        ({"episode_max_tasks": 1}, Termination.TASKS_EXHAUSTED),
        ({"max_decompositions": 1}, Termination.DECOMPOSITIONS_EXHAUSTED),
    ],
)
def test_episode_limits_produce_failed_outcomes_and_run_end(tmp_path, limit, expected):
    fake = build_fake(tmp_path, task=every(1), episode=never, run=never, tasks_per_plan=1)
    configure(fake, max_episodes=1, **limit)

    result = fake.harness.run("r1", [GOAL])

    assert result.outcomes[0].termination is expected
    assert not result.outcomes[0].success
    assert_mechanical_tail(fake)


def test_task_clamp_records_both_values_without_changing_the_input(tmp_path):
    fake = build_fake(tmp_path)
    task_input = TaskInput(
        entry_id=(GOAL.model_copy(update={"max_steps": 30})).task_id,
        run_id="r1",
        episode_id="r1-ep1",
        total_acts=0,
        task=GOAL.model_copy(update={"max_steps": 30}),
    )

    state = begin_task(fake.run_rt.episode.task, task_input)

    assert task_input.task.max_steps == 30 and state.task.max_steps == 12
    clamp = next(event for event in events(fake) if event.kind == TraceKind.BUDGET_CLAMPED)
    assert json.loads(clamp.content) == {"original": "30", "clamped": "12"}


def test_restored_action_and_decomposition_counters_do_not_reset(tmp_path):
    fake = build_fake(tmp_path)
    configure(fake, max_total_actions=3)
    run = RunState(
        run_id="r1",
        run_goal=Goal(goal="g", criteria="c"),
        goals=[GoalEntry(task=GOAL)],
        actions_used=3,
        total_acts=3,
    )
    restored = RunState.model_validate_json(run.model_dump_json())

    final = compile_run_graph().invoke(restored, context=fake.run_rt)

    assert final["actions_used"] == 3
    assert final["termination"] is Termination.ACTIONS_EXHAUSTED
    assert_mechanical_tail(fake)
    ep = EpisodeRunState(
        run_id="r1",
        episode_id="r1-ep1",
        goal=GOAL,
        ep_ctx=EpisodeContext(),
        decompositions_used=2,
        run_goal="测试总目标",
    )
    configure(fake, max_decompositions=2)
    final_ep = fake.run_rt.episode_graph.invoke(
        EpisodeRunState.model_validate_json(ep.model_dump_json()),
        context=fake.run_rt.episode,
    )
    assert final_ep["decompositions_used"] == 2
    assert final_ep["termination"] is Termination.DECOMPOSITIONS_EXHAUSTED


def test_remaining_time_snapshot_only_tightens_a_restored_deadline():
    clock = Clock()
    deadline = Deadline(600, 60, 3, clock=clock)
    deadline.start(100)
    clock.now += 10

    deadline.cap_remaining(200)
    assert deadline.remaining() == 90
    deadline.cap_remaining(50)
    assert deadline.remaining() == 50


def test_missing_task_steps_still_use_the_existing_parse_retry():
    raw = '{"tasks":[{"goal":"g","success_criteria":"c"}]}'
    provider = ScriptedLLM(text_reply(raw), text_reply(raw))
    decomposer = Decomposer(
        Brain(plan_llm=provider), policy=call_policy(), prompt_gateway=PromptGateway(None)
    )
    req = FromHarnessToBrainToolDecomposeReq(
        goal=Goal(goal="g", criteria="c"),
        observation=TaskObservation(step=0, status="s", scene=TaskScene.WALK),
        max_tasks=2,
    )

    with pytest.raises(MaxRetriesExceeded) as caught:
        decomposer.decompose(req)

    assert len(provider.requests) == 2
    assert [call.error_kind for call in caught.value.calls] == ["ParseFailure", "ParseFailure"]
    assert all(call.payload["raw"] == raw for call in caught.value.calls)


def test_state_schema_is_frozen_after_the_l1_goal_identity_stamp():
    assert state_schema_hash() == "95057cca4fffb08b"
