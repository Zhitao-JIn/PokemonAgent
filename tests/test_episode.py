"""集成测试 —— **这个文件就是项目的使用说明书**。

一个完整的 episode：装配、跑图、读结果、读 trace。
想知道这套东西怎么用，从 test_agent_completes_the_demo_task 读起。
"""

from __future__ import annotations

from pokemon_agent.graph.build import build_demo
from pokemon_agent.mocks.fake_llm import FakeLLM
from pokemon_agent.mocks.mock_world import DEMO_TASK


def test_agent_completes_the_demo_task():
    """端到端：拿药水 → 走到道馆 → 击败馆主。

    脚本是这条最优路径：
        HOME -> ROUTE(捡药水) -> SHOP -> GYM -> 打赢
    """
    from pokemon_agent.graph.build import AgentState

    llm = FakeLLM.scripted([
        ("先去 ROUTE", "move_forward"),
        ("地上有药水，捡起来", "pick_up"),
        ("继续走", "move_forward"),
        ("到道馆去", "move_forward"),
        ("有药水了，开打", "fight_gym"),
    ])
    graph, harness, trace = build_demo(llm)

    final = graph.invoke(AgentState(episode_id="ep-1", task=DEMO_TASK))

    outcome = final["outcome"]
    assert outcome.success is True
    assert outcome.reason == "success"
    assert outcome.steps == 5


def test_trace_event_ids_are_strictly_increasing():
    """trace 的核心不变量：event_id 严格单调。

    SSE 的断线补发完全依赖它——一旦重复或回退，观测台会静默丢事件。
    """
    from pokemon_agent.graph.build import AgentState

    llm = FakeLLM.scripted([
        ("走", "move_forward"),
        ("捡", "pick_up"),
        ("走", "move_forward"),
        ("走", "move_forward"),
        ("打", "fight_gym"),
    ])
    graph, _, trace = build_demo(llm)
    graph.invoke(AgentState(episode_id="ep-1", task=DEMO_TASK))

    ids = [e.event_id for e in trace.all_events()]

    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_replay_returns_only_the_asked_episode_after_a_cursor():
    """replay 的两个用途：按 episode 过滤，以及 SSE 断线后从游标续传。"""
    from pokemon_agent.graph.build import AgentState

    llm = FakeLLM.scripted([("走", "move_forward")], loop=True)
    graph, _, trace = build_demo(llm)
    graph.invoke(AgentState(episode_id="ep-1", task=DEMO_TASK))

    events = list(trace.replay("ep-1"))
    cursor = events[2].event_id
    resumed = list(trace.replay("ep-1", after_event_id=cursor))

    assert all(e.episode_id == "ep-1" for e in events)
    assert all(e.event_id > cursor for e in resumed)
    assert list(trace.replay("ep-does-not-exist")) == []


def test_failing_the_task_by_running_out_of_steps():
    """失败路径同样要能跑通并给出结构化结果。"""
    from pokemon_agent.graph.build import AgentState

    llm = FakeLLM.scripted([("原地打转", "move_back")], loop=True)
    graph, _, _ = build_demo(llm)

    final = graph.invoke(AgentState(episode_id="ep-2", task=DEMO_TASK))

    outcome = final["outcome"]
    assert outcome.success is False
    assert outcome.reason == "max_steps_exceeded"
    assert outcome.steps == DEMO_TASK.max_steps
