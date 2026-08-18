"""单元测试 —— 大脑怎么用，以及它保证了什么。

这些测试的第一读者是"想知道 ReActBrain 怎么用"的人（CLAUDE.md 第三节第 5 条），
所以每个测试都是一段完整可读的用法示范，不是覆盖率任务。
"""

from __future__ import annotations

import json

import pytest

from pokemon_agent.brain.react import ReActBrain
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.mocks.mock_harness import MockHarness
from pokemon_agent.mocks.mock_trace import MockTrace
from pokemon_agent.mocks.fake_llm import FakeLLM
from pokemon_agent.mocks.mock_world import DEMO_ACTION_DESCRIPTIONS, DEMO_TASK, MockWorld
from pokemon_agent.schemas.core import EventType


def make_brain(llm: FakeLLM) -> tuple[ReActBrain, MockHarness, MockTrace]:
    """最小装配：三行就能得到一个可用的大脑。

    注意 brain 拿到的三个参数都是接口类型，它不知道背后是 mock。
    """
    trace = MockTrace()
    harness = MockHarness(MockWorld(), trace, action_descriptions=DEMO_ACTION_DESCRIPTIONS)
    brain = ReActBrain(llm, harness, trace)
    return brain, harness, trace


def test_brain_picks_the_scripted_action():
    """最简单的正确用法：给定观测和动作空间，大脑选出一个动作。"""
    llm = FakeLLM.scripted([("先往前走", "move_forward")])
    brain, harness, _ = make_brain(llm)

    obs = harness.start_episode("ep-1", DEMO_TASK)
    action = brain.choose("ep-1", obs, harness.get_action_space())

    assert action.name == "move_forward"
    assert action.thought == "先往前走"


def test_brain_never_returns_an_action_outside_the_space():
    """核心主张：大脑不会把幻觉动作递出去。

    脚本让模型先选一个不存在的动作，再选一个合法的——
    第一次被 IllegalAction 拦下并重试，最终返回的一定在动作空间内。
    """
    llm = FakeLLM([
        json.dumps({"thought": "乱选", "action": "fly_to_moon", "args": {}}),
        json.dumps({"thought": "改成合法的", "action": "move_forward", "args": {}}),
    ])
    brain, harness, trace = make_brain(llm)

    obs = harness.start_episode("ep-1", DEMO_TASK)
    space = harness.get_action_space()
    action = brain.choose("ep-1", obs, space)

    assert space.contains(action.name)
    assert llm.call_count == 2, "非法动作应当触发一次重试"
    assert trace.count("ep-1", EventType.ERROR) == 1, "失败要留在 trace 里，不能静默"


def test_bad_json_is_retried_and_counted():
    """坏 JSON 走 ParseFailure 重试。

    ParseFailure 与 IllegalAction 分开，是因为在 replay 里它们是不同的失败模式：
    前者说明格式没学会，后者说明模型在幻觉动作。
    """
    llm = FakeLLM([
        "这不是 JSON",
        json.dumps({"thought": "重来", "action": "move_forward", "args": {}}),
    ])
    brain, harness, trace = make_brain(llm)

    obs = harness.start_episode("ep-1", DEMO_TASK)
    action = brain.choose("ep-1", obs, harness.get_action_space())

    assert action.name == "move_forward"
    assert trace.count("ep-1", EventType.ERROR) == 1


def test_giving_up_after_max_retries_is_an_explicit_failure():
    """连续失败不是"再试试就好"，是一类要被统计的失败模式。"""
    llm = FakeLLM(["坏输出"], loop=True)
    brain, harness, trace = make_brain(llm)
    brain = ReActBrain(llm, harness, trace, max_retries=2)

    obs = harness.start_episode("ep-1", DEMO_TASK)
    space = harness.get_action_space()

    with pytest.raises(MaxRetriesExceeded):
        brain.choose("ep-1", obs, space)

    assert llm.call_count == 2
    # 两次解析失败 + 一次放弃 = 三条 ERROR
    assert trace.count("ep-1", EventType.ERROR) == 3


def test_empty_action_space_is_a_caller_bug():
    """precondition 示范：空动作空间是 harness 的 bug，大脑就地爆炸而不是兜底。"""
    from pokemon_agent.schemas.core import ActionSpace

    brain, harness, _ = make_brain(FakeLLM.scripted([("x", "move_forward")]))
    obs = harness.start_episode("ep-1", DEMO_TASK)

    with pytest.raises(AssertionError):
        brain.choose("ep-1", obs, ActionSpace(names=[]))
