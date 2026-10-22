"""假时钟下的请求、重试与 provider 总等待预算，无真实模型或网络。"""

import importlib
import json

import pytest
from _doubles.llm import ScriptedLLM, text_reply
from _harness_fixtures.app_config import call_policy

from pokemon_agent.brain import Brain, Goal
from pokemon_agent.brain.errors import ToolTimeout
from pokemon_agent.brain.providers import DeepSeekProvider
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq
from pokemon_agent.deadline import Deadline
from pokemon_agent.direct.brain_tool import Planner
from pokemon_agent.direct.budget_provider import BudgetProvider
from pokemon_agent.errors import BudgetExhausted
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq


class Clock:
    """单调假时钟；只有被测请求或退避明确推进。"""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def plan_request():
    return FromHarnessToBrainToolPlanOnceReq(
        run_goal=Goal(goal="测试父目标", criteria="测试父验收条件"),
        run_id="budget",
        plan=[],
        max_push=3,
    )


def plan_reply():
    return text_reply('{"updates": [], "why": "scripted", "new_items": []}')


def test_deadline_uses_one_clock_and_preserves_the_reserve():
    clock = Clock()
    deadline = Deadline(600, 60, 3, clock=clock)

    clock.advance(500)

    assert deadline.remaining() == 100
    assert deadline.allowed(45, "plan") == 40
    clock.advance(38)
    with pytest.raises(BudgetExhausted):
        deadline.allowed(45, "plan")
    clock.advance(70)
    assert deadline.remaining() == 0


def test_insufficient_remaining_time_never_calls_the_brain_provider():
    clock = Clock()
    provider = ScriptedLLM(plan_reply())
    deadline = Deadline(100, 60, 3, clock=clock)
    planner = Planner(
        Brain(plan_llm=provider),
        policy=call_policy(),
        deadline=deadline,
        prompt_gateway=PromptGateway(None),
    )
    clock.advance(38)

    with pytest.raises(BudgetExhausted) as caught:
        planner.plan(plan_request())

    assert provider.requests == []
    assert caught.value.source == "plan" and caught.value.calls == []


@pytest.mark.parametrize("first_duration, expected_requests", [(38, 1), (10, 2)])
def test_retries_share_remaining_time_and_keep_completed_failure_calls(
    monkeypatch, first_duration, expected_requests
):
    clock = Clock()

    class SlowProvider(ScriptedLLM):
        def complete(self, req):
            clock.advance(first_duration if not self.requests else 1)
            return super().complete(req)

    provider = SlowProvider(ToolTimeout("scripted timeout"), plan_reply())
    deadline = Deadline(100, 60, 3, clock=clock)
    planner = Planner(
        Brain(plan_llm=provider),
        policy=call_policy(max_attempts=2),
        deadline=deadline,
        prompt_gateway=PromptGateway(None),
    )
    monkeypatch.setattr("pokemon_agent.direct.brain_tool.time.sleep", clock.advance)

    if expected_requests == 1:
        with pytest.raises(BudgetExhausted) as caught:
            planner.plan(plan_request())
        assert len(caught.value.calls) == 1
        assert caught.value.calls[0].error_kind == "ToolTimeout"
    else:
        result = planner.plan(plan_request())
        assert result.plan.why == "scripted" and len(result.calls) == 2

    assert len(provider.requests) == expected_requests


def test_without_a_run_deadline_the_production_request_can_complete():
    provider = ScriptedLLM(plan_reply())
    planner = Planner(
        Brain(plan_llm=provider),
        policy=call_policy(),
        deadline=None,
        prompt_gateway=PromptGateway(None),
    )

    response = planner.plan(plan_request())

    assert response.plan.why == "scripted" and len(provider.requests) == 1


@pytest.mark.parametrize("with_image", [False, True])
def test_provider_override_caps_socket_and_total_wait_without_an_extra_fifteen_seconds(
    monkeypatch, with_image
):
    module = importlib.import_module("pokemon_agent.brain.providers")
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 2},
                }
            ).encode()

    def urlopen(req, timeout):
        observed["socket"] = timeout
        return Response()

    class Future:
        def __init__(self, work):
            self.work = work

        def result(self, timeout):
            observed["total"] = timeout
            return self.work()

    class Executor:
        def submit(self, work):
            return Future(work)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(module, "_POST_POOL", Executor())
    clock = Clock()
    deadline = Deadline(100, 60, 3, clock=clock)
    clock.advance(28)
    provider = BudgetProvider(DeepSeekProvider(temperature=0.0), deadline, 45, "plan")

    if with_image:
        provider.describe(VisionDescribeReq(prompt="json", images=["data:image/png;base64,AA=="]))
    else:
        provider.complete(LlmCompleteReq(prompt="json"))

    assert observed == {"socket": 12, "total": 12}
    assert provider.config()["request_timeout_s"] == "45"


def test_a_transport_timeout_can_exhaust_the_run_before_retrying(monkeypatch):
    module = importlib.import_module("pokemon_agent.brain.providers")
    clock = Clock()
    submitted = []

    class Future:
        def result(self, timeout):
            clock.advance(timeout)
            raise TimeoutError("scripted hanging request")

    class Executor:
        def submit(self, work):
            submitted.append(work)
            return Future()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    monkeypatch.setattr(module, "_POST_POOL", Executor())
    deadline = Deadline(100, 60, 3, clock=clock)
    provider = BudgetProvider(DeepSeekProvider(temperature=0.0), deadline, 45, "plan")
    planner = Planner(
        Brain(plan_llm=provider),
        policy=call_policy(),
        deadline=deadline,
        prompt_gateway=PromptGateway(None),
    )

    with pytest.raises(BudgetExhausted) as caught:
        planner.plan(plan_request())

    assert len(submitted) == 1
    assert len(caught.value.calls) == 1
    assert deadline.remaining() == 60
