"""RAM 读数经真实 tool/prompt 传给 run 判定，并留在独立评分复用的文字材料中。"""

import json
from collections.abc import Sequence

import pytest
from _harness_fixtures.app_config import call_policy
from _harness_fixtures.brain import _Brain
from inspect_ai.util import Store
from inspect_ai.util._store import init_subtask_store
from pydantic import ValidationError

from evals.agent_short_goal_run.scorer.result_grade import final_evidence
from evals.agent_short_goal_run.solver.record import AgentRunRecord
from pokemon_agent.brain import Goal
from pokemon_agent.brain.interface import JudgeResult, ModelCall
from pokemon_agent.direct.brain_tool import Judger
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq, TraceEvent
from pokemon_agent.schemas.harness.domain.ram_observation import RamObservation


@pytest.fixture(autouse=True)
def _fresh_store() -> None:
    """本文件用裸 AgentRunRecord 读 trace；StoreModel 读字段优先取 ambient store，同一进程里
    先跑的 evals 用例会留下旧 work_dir。inspect_ai.util 没有公开的 store 上下文入口，只能借私有的
    init_subtask_store 换一个空 store。"""
    init_subtask_store(Store())


class _RecordingBrain(_Brain):
    """实现同一 Brain 契约，记录最终模型输入而不调用 API。"""

    def __init__(self) -> None:
        super().__init__(
            task=lambda _: False, episode=lambda _: False, run=lambda _: False, tasks_per_plan=1
        )
        self.prompt = ""
        self.calls = 0

    def judge(
        self, *, prompt: str, goal: str, history: Sequence[str], images: Sequence[str] = ()
    ) -> JudgeResult:
        """记录素材，返回可解析结论。"""
        self.prompt = prompt
        self.calls += 1
        return JudgeResult(decision="continue", why="证据已收到", calls=[ModelCall(payload={})])


def _reading() -> RamObservation:
    """满血读数来自结构化 RAM，不来自画面文字或模型总结。"""
    return RamObservation(
        event_id="ram-event",
        source="run.sense",
        episode_id="e",
        task_id="t",
        step=4,
        observed_at=100.0,
        sequence=4,
        ram={
            "in_battle": False,
            "covered": True,
            "text_source": "decode",
            "menu": {"current_item": 0, "max_item": 0, "top_x": 0},
            "money": 100,
            "bag": [],
            "party": [{"species": 1, "level": 7, "hp": 25, "max_hp": 25, "status": "ok"}],
            "decoded": {"dialog_text": "", "options": [], "cursor": ""},
        },
    )


def test_run_judge_and_result_grader_receive_the_same_numeric_evidence(tmp_path) -> None:
    request = FromHarnessToBrainToolJudgeReq(
        goal=Goal(goal="核对状态", criteria="字段符合目标值"), ram_observations=[_reading()]
    )
    brain = _RecordingBrain()

    Judger(brain, policy=call_policy(), prompt_gateway=PromptGateway(None)).judge(request)

    assert brain.calls == 1
    assert '"hp":25,"max_hp":25' in brain.prompt
    assert "trace=ram-event" in brain.prompt and "source=run.sense" in brain.prompt
    assert brain.prompt.count("trace=ram-event") == 1
    assert brain.prompt.index("## 最近 RAM 观测怎么读") < brain.prompt.index("## 本次输入")
    trace = tmp_path / "trace"
    trace.mkdir()
    event = TraceEvent(
        uuid="judge-call",
        seq=5,
        kind="judge_call",
        type="model_call",
        started_at=101,
        ended_at=102,
        meta=json.dumps(
            {
                "run_id": "r",
                "branch": "main",
                "source": "run.review_and_judge",
                "episode_id": "r",
                "task_id": "r",
                "step": 1,
            }
        ),
        content=json.dumps(
            {
                "prompt_task": "judge_success",
                "prompt": brain.prompt,
                "raw": "continue",
                "images": [],
            }
        ),
    )
    (trace / "judge-call.json").write_text(event.model_dump_json(), encoding="utf-8")
    record = AgentRunRecord(run_id="r", work_dir=str(tmp_path), branch="main")
    assert final_evidence(record, "local") == brain.prompt


def test_legacy_request_does_not_invent_ram_material() -> None:
    request = FromHarnessToBrainToolJudgeReq(goal=Goal(goal="目标", criteria="条件"))
    brain = _RecordingBrain()

    Judger(brain, policy=call_policy(), prompt_gateway=PromptGateway(None)).judge(request)

    assert request.ram_observations == []
    assert request.model_dump(mode="json")["ram_observations"] == []
    assert "（本次未提供 RAM 观测）" not in brain.prompt
    assert "最近 RAM 观测" not in brain.prompt


def test_judge_request_rejects_more_than_five_ram_observations() -> None:
    with pytest.raises(ValidationError):
        FromHarnessToBrainToolJudgeReq(
            goal=Goal(goal="目标", criteria="条件"), ram_observations=[_reading()] * 6
        )
