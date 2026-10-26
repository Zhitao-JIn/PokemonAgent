"""经真实装配与provider发送节点开关；HTTP替身保证不访问密钥文件或外网。"""

import json
from typing import Literal

import pytest
from _doubles.frames import solid_frame
from _doubles.http import FakeUrlopen, ok_body

from pokemon_agent.brain import Goal
from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeTaskReq,
    FromHarnessToBrainToolVerifyReq,
)
from pokemon_agent.schemas.memory import ActMemory, EpisodeMemory, TaskMemory
from pokemon_agent.settings import ModelsConfig, load_config


def tools(
    model: str,
    layer: Literal["run", "episode", "task"],
    overrides: dict[str, bool],
    default_thinking: bool = True,
) -> BrainTool:
    """装配真实tool，所有链路同型号便于核对节点隔离而不是型号差异。"""
    app = load_config().config
    data = app.models.model_dump(mode="json")
    for name in ["text", "judge", "verify", "plan"]:
        data[name].update(model=model, thinking=default_thinking, cache_marker=None)
    data["node_thinking"] = overrides
    return BrainTool.build(
        links=("text", "judge", "verify", "plan"),
        models=ModelsConfig.model_validate_json(json.dumps(data)),
        layer=layer,
        retry=app.retry,
        request_timeouts=app.request_timeouts_s,
        action_limits=app.action_limits,
        image_cap=app.memory.scope_image_cap,
    )


@pytest.fixture(autouse=True)
def isolated_http(monkeypatch: pytest.MonkeyPatch) -> FakeUrlopen:
    """用测试密钥与录制HTTP替身隔离所有provider。"""
    for key in [
        "DASHSCOPE_API_KEY",
        "ARK_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ]:
        monkeypatch.setenv(key, "test-only")
    fake = FakeUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


def response(fake: FakeUrlopen, model: str, raw: str) -> None:
    """设置与厂商协议匹配的响应，足量输入覆盖带图交付检查。"""
    fake.next_body = (
        {
            "content": [{"type": "text", "text": raw}],
            "usage": {"input_tokens": 3000, "output_tokens": 10},
            "stop_reason": "end_turn",
        }
        if model.startswith("claude")
        else ok_body(text=raw, prompt_tokens=3000)
    )


def sent_thinking(body: dict[str, object]) -> bool:
    """按厂商HTTP协议读取实际发送开关。"""
    if "enable_thinking" in body:
        return bool(body["enable_thinking"])
    if "thinking" in body:
        return body["thinking"]["type"] != "disabled"
    return body["reasoning_effort"] != "none"


@pytest.mark.parametrize(
    "model",
    ["qwen3.8-flash", "deepseek-flash", "doubao-seed-1-6-250615", "claude-haiku-5-5", "gpt-6-luna"],
)
@pytest.mark.parametrize("with_image", [False, True])
@pytest.mark.parametrize("default_thinking", [False, True])
def test_node_switch_isolated_across_layers_and_providers(
    model: str, with_image: bool, default_thinking: bool, isolated_http: FakeUrlopen
) -> None:
    overrides = {"run.judge": False, "task.judge": True}
    run = tools(model, "run", overrides, default_thinking)
    task = tools(model, "task", overrides, default_thinking)
    history = [
        TaskMemory(
            run_id="r",
            episode_id="e",
            task_id="t",
            goal="g",
            steps_used=1,
            total_acts=1,
            summary="s",
            quality_score=0.5,
            quality_rationale="q",
            first_frame=solid_frame((0, 0, 0)) if with_image else None,
        )
    ]
    req = FromHarnessToBrainToolJudgeReq(goal=Goal(goal="g", criteria="c"), task_memories=history)
    response(isolated_http, model, '{"decision":"continue","why":"need evidence"}')

    first = run.judger.judge(req)
    second = task.judger.judge(req)
    third = run.judger.judge(req)

    assert [sent_thinking(x["json"]) for x in isolated_http.calls] == [False, True, False]
    for result, node, value in [
        (first, "run.judge", "false"),
        (second, "task.judge", "true"),
        (third, "run.judge", "false"),
    ]:
        assert result.calls[0].payload["thinking_node"] == node
        assert result.calls[0].payload["thinking_effective"] == value


def test_verify_and_episode_summary_can_use_opposite_switches(isolated_http: FakeUrlopen) -> None:
    tool = tools("deepseek-flash", "episode", {"episode.verify": True, "episode.summarize": False})
    response(isolated_http, "deepseek-flash", '{"verdicts":[]}')
    verified = tool.verifier.verify(FromHarnessToBrainToolVerifyReq(entries=[], goal="g"))
    entry = TaskMemory(
        run_id="r",
        episode_id="e",
        task_id="t",
        goal="g",
        steps_used=1,
        total_acts=1,
        summary="s",
        quality_score=0.5,
        quality_rationale="q",
    )
    response(
        isolated_http,
        "deepseek-flash",
        '{"summary":"s","quality_score":0.5,"quality_rationale":"q","markdown":"m"}',
    )

    summary = tool.summarizer.summarize(
        FromHarnessToBrainToolSummarizeReq(
            entries=[entry],
            verdicts=[],
            episode_id="e",
            run_id="r",
            run_goal="g",
            goal="g",
            termination="goal_done",
            steps=1,
            max_steps=2,
        )
    )

    assert [sent_thinking(x["json"]) for x in isolated_http.calls] == [True, False]
    assert verified.calls[0].payload["thinking_node"] == "episode.verify"
    assert summary.calls[0].payload["thinking_effective"] == "false"


def test_unconfigured_node_inherits_its_link(isolated_http: FakeUrlopen) -> None:
    tool = tools("deepseek-flash", "episode", {"task.judge": False})
    response(isolated_http, "deepseek-flash", '{"decision":"continue","why":"check"}')

    result = tool.judger.judge(FromHarnessToBrainToolJudgeReq(goal=Goal(goal="g", criteria="c")))

    assert sent_thinking(isolated_http.calls[0]["json"]) is True
    assert result.calls[0].payload["thinking_node"] == "episode.judge"


def summary_requests() -> tuple[
    FromHarnessToBrainToolSummarizeRunReq, FromHarnessToBrainToolSummarizeTaskReq
]:
    """最小run/task摘要素材，供公开门面隔离用例使用。"""
    episode = EpisodeMemory(
        run_id="r",
        run_goal="g",
        episode_id="e",
        goal="g",
        steps=1,
        summary="s",
        quality_score=0.5,
        quality_rationale="q",
    )
    run_req = FromHarnessToBrainToolSummarizeRunReq(
        run_id="r",
        run_goal="g",
        goals=[],
        episode_memories=[episode],
        termination="goal_done",
        judge_reason="q",
        episodes=1,
        succeeded=1,
        acts_used=1,
        max_episodes=2,
    )
    act = ActMemory(
        episode_id="e",
        task_id="t",
        step=0,
        action="a",
        before=ActMemory.Observation(facts={}, step=0),
        after=ActMemory.Observation(facts={}, step=1),
    )
    task_req = FromHarnessToBrainToolSummarizeTaskReq(
        entries=[act],
        verdicts=[],
        entry_id="entry",
        task_id="t",
        episode_id="e",
        run_id="r",
        goal="g",
        termination="goal_done",
        steps_used=1,
        max_steps=2,
    )
    return run_req, task_req


def test_run_and_task_summaries_do_not_inherit_episode_summary_override(
    isolated_http: FakeUrlopen,
) -> None:
    tool = tools(
        "deepseek-flash",
        "episode",
        {"episode.summarize": False, "run.summarize": False, "task.summarize": True},
    )
    run_req, task_req = summary_requests()
    response(
        isolated_http,
        "deepseek-flash",
        '{"summary":"s","quality_score":0.5,"quality_rationale":"q","markdown":"m"}',
    )

    run = tool.run_summarizer.summarize_run(run_req)
    task = tool.task_summarizer.summarize_task(task_req)

    assert [sent_thinking(x["json"]) for x in isolated_http.calls] == [False, True]
    assert run.calls[0].payload["thinking_node"] == "run.summarize"
    assert task.calls[0].payload["thinking_node"] == "task.summarize"


def test_node_thinking_does_not_override_empty_completion_retry_fallback(
    monkeypatch: pytest.MonkeyPatch, isolated_http: FakeUrlopen
) -> None:
    from evals.brain_plan.dataset import load

    tool = tools("deepseek-flash", "run", {"run.plan": True})
    invalid = ok_body(text="")
    valid = ok_body(text='{"new_items":[],"execution_order":null,"why":"keep"}')
    bodies = iter([invalid, valid])

    def replies(req: object, timeout: float | None = None) -> object:
        isolated_http.next_body = next(bodies)
        return isolated_http(req, timeout=timeout)

    monkeypatch.setattr("urllib.request.urlopen", replies)
    monkeypatch.setattr("pokemon_agent.direct.brain_tool.time.sleep", lambda _: None)

    result = tool.planner.plan(load("v20261020_1846")[0].request)

    assert [sent_thinking(x["json"]) for x in isolated_http.calls] == [True, False]
    assert [x.payload["thinking_effective"] for x in result.calls] == ["true", "false"]
    assert result.calls[0].error_kind == "EmptyCompletion"
