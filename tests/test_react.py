"""单元测试 —— 大脑怎么用，以及它保证了什么。

这些测试的第一读者是"想知道 ReActBrain 怎么用"的人（CLAUDE.md 第三节第 5 条），
所以每个测试都是一段完整可读的用法示范，不是覆盖率任务。
"""

from __future__ import annotations

import json

import pytest

from pokemon_agent.brain.react import ReActBrain
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.mocks.fake_llm import FakeLLM
from pokemon_agent.mocks.mock_harness import MockHarness
from pokemon_agent.mocks.mock_trace import MockTrace
from pokemon_agent.mocks.mock_world import DEMO_ACTION_DESCRIPTIONS, DEMO_TASK, MockWorld
from pokemon_agent.schemas.core import MAX_RATIONALE, EventType


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
        json.dumps({"thought": "乱选", "rationale": ["想飞"], "action": "fly_to_moon"}),
        json.dumps({"thought": "改成合法的", "rationale": ["前面有路"], "action": "move_forward"}),
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
        json.dumps({"thought": "重来", "rationale": ["前面有路"], "action": "move_forward"}),
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


def test_missing_rationale_is_its_own_failure_mode():
    """论据缺失单独成一类 reason，不和"格式坏"混在一起。

    replay 要靠这个拆开两种失败：JSON 解析不出来是格式问题（改 prompt 或上约束解码），
    给了合法 JSON 但不肯给论据是另一回事（改动作说明或加示例）。
    """
    llm = FakeLLM([
        json.dumps({"thought": "懒得说理由", "action": "move_forward"}),
        json.dumps({"thought": "补上", "rationale": ["前面有路"], "action": "move_forward"}),
    ])
    brain, harness, trace = make_brain(llm)

    obs = harness.start_episode("ep-1", DEMO_TASK)
    action = brain.choose("ep-1", obs, harness.get_action_space())

    assert action.rationale == ["前面有路"]
    errors = [e for e in trace.all_events() if e.type is EventType.ERROR]
    assert len(errors) == 1
    assert "missing 'rationale' field" in errors[0].payload["reason"]


def test_a_single_rationale_may_be_written_as_a_bare_string():
    """容忍 `"rationale": "..."`——常见格式偏差，语义无歧义，不该消耗一次重试。"""
    llm = FakeLLM([
        json.dumps({"thought": "想", "rationale": "前面有路", "action": "move_forward"}),
    ])
    brain, harness, trace = make_brain(llm)

    obs = harness.start_episode("ep-1", DEMO_TASK)
    action = brain.choose("ep-1", obs, harness.get_action_space())

    assert action.rationale == ["前面有路"]
    assert llm.call_count == 1, "格式容忍不该触发重试"
    assert trace.count("ep-1", EventType.ERROR) == 0


def test_too_many_rationale_items_is_rejected_not_truncated():
    """超上限打回重试，**不悄悄截断**。

    模型认为有 N 条是承重的，替它丢掉一条就是做了一个没有记录的决定。
    """
    too_many = [f"论据{i}" for i in range(MAX_RATIONALE + 1)]
    llm = FakeLLM([
        json.dumps({"thought": "说太多", "rationale": too_many, "action": "move_forward"}),
        json.dumps({"thought": "收敛", "rationale": ["前面有路"], "action": "move_forward"}),
    ])
    brain, harness, trace = make_brain(llm)

    obs = harness.start_episode("ep-1", DEMO_TASK)
    action = brain.choose("ep-1", obs, harness.get_action_space())

    assert action.rationale == ["前面有路"]
    errors = [e for e in trace.all_events() if e.type is EventType.ERROR]
    assert "too many rationale items" in errors[0].payload["reason"]


def test_memory_records_the_rationale_not_the_thought():
    """进记忆的是论据，完整推理只留在 trace 里。

    这是整套设计的落点：记忆条目"我以为 P，结果 R"是自带标签的，
    而推理过程属于本次决策的算力，用完即弃。
    """
    llm = FakeLLM([
        json.dumps({
            "thought": "这是一段很长的推理过程，包含大量与以后无关的中间步骤",
            "rationale": ["地上有药水而我手上没有"],
            "action": "move_forward",
        }),
    ])
    brain, harness, _ = make_brain(llm)

    obs = harness.start_episode("ep-1", DEMO_TASK)
    action = brain.choose("ep-1", obs, harness.get_action_space())
    brain.remember("ep-1", obs, action, "你走到了 ROUTE")

    (entry,) = harness.memory_query(obs.summary)
    assert "地上有药水而我手上没有" in entry.content
    assert "中间步骤" not in entry.content


def test_empty_action_space_is_a_caller_bug():
    """precondition 示范：空动作空间是 harness 的 bug，大脑就地爆炸而不是兜底。"""
    from pokemon_agent.schemas.core import ActionSpace

    brain, harness, _ = make_brain(FakeLLM.scripted([("x", "move_forward")]))
    obs = harness.start_episode("ep-1", DEMO_TASK)

    with pytest.raises(AssertionError):
        brain.choose("ep-1", obs, ActionSpace(names=[]))
