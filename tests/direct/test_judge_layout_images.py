"""judge v11 与固定 v8 经相同 tool 收到完全相同的截图序列。"""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from _harness_fixtures.app_config import call_policy
from _harness_fixtures.brain import _Brain

from pokemon_agent.brain.interface import JudgeResult, ModelCall
from pokemon_agent.direct.brain_tool import Judger
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq
from tests.prompt.judge_layout_examples import old_gateway, requests


class RecordingBrain(_Brain):
    """同一 BrainPort 的本地实现，只记录渲染文本和图片。"""

    def __init__(self) -> None:
        super().__init__(
            task=lambda _: False, episode=lambda _: False, run=lambda _: False, tasks_per_plan=1
        )
        self.images: list[str] = []
        self.prompt = ""

    def judge(
        self, *, prompt: str, goal: str, history: Sequence[str], images: Sequence[str] = ()
    ) -> JudgeResult:
        """记录真实 tool 入参，返回固定判定，不调用模型。"""
        self.images = list(images)
        self.prompt = prompt
        return JudgeResult(decision="continue", why="继续核对", calls=[ModelCall(payload={})])


def image_request(layer: str) -> FromHarnessToBrainToolJudgeReq:
    """重复边界帧去重，首末帧与层间数量帽均可观察。"""
    request = requests()[layer]
    if request.history:
        first = request.history[0].model_copy(update={"before_frame": "A", "after_frame": "B"})
        second = first.model_copy(update={"step": 2, "before_frame": "B", "after_frame": "C"})
        return request.model_copy(update={"history": [first, second]})
    field = "task_memories" if layer == "episode" else "episode_memories"
    original = getattr(request, field)[0]
    first = original.model_copy(update={"first_frame": "A", "last_frame": "B"})
    second = original.model_copy(update={"first_frame": "B", "last_frame": "C"})
    return request.model_copy(update={field: [first, second]})


@pytest.mark.parametrize("layer", ["task", "episode", "run"])
def test_image_sequence_deduplication_and_caps_match_v8(layer: str, tmp_path: Path) -> None:
    request = image_request(layer)
    policy = replace(call_policy(), image_cap=2)
    images: list[list[str]] = []

    for gateway in (old_gateway(tmp_path), PromptGateway(None)):
        brain = RecordingBrain()
        Judger(brain, policy=policy, prompt_gateway=gateway).judge(request)
        images.append(brain.images)
        assert "之后变成" in brain.prompt if layer == "task" else "全文末句。" in brain.prompt

    assert images[0] == images[1] == (["A", "B", "C"] if layer == "task" else ["B", "C"])
