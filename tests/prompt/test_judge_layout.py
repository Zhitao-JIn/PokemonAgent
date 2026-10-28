"""三层判定共享布局，执行证据与规划主张完整且位置固定。"""

import pytest

from pokemon_agent.direct.judge_prompt_params import judge_prompt_params
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolJudgeReq
from tests.prompt.judge_layout_examples import params

BLOCKS = (
    "规则",
    "检索知识",
    "目标",
    "背景索引",
    "本层历史",
    "地图交互事实",
    "状态与反馈",
    "当前现场",
    "预算与进度",
    "人类插话",
)


def test_ram_metadata_and_full_json_follow_current_observation() -> None:
    material = params()["run"]
    text = PromptGateway(None).render("judge_success", material).text
    frame = text.split("\n## 当前现场\n", 1)[1]

    assert frame.index("- overlay: none") < frame.index("### 最近 RAM 观测")
    assert "known_objects" not in frame
    for number, entry in enumerate(material.ram_observations, start=1):
        line = (
            f"观测 {number}｜time={entry.observed_at}｜seq={entry.sequence}｜source={entry.source}"
            f"｜step={entry.step}｜trace={entry.event_id}\n{entry.ram_json}"
        )
        assert text.count(line) == 1
    assert [frame.index(e.event_id) for e in material.ram_observations] == sorted(
        frame.index(e.event_id) for e in material.ram_observations
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_omitted_and_empty_ram_have_the_same_contract_and_prompt(explicit: bool) -> None:
    data = {"goal": {"goal": "目标", "criteria": "判据"}}
    omitted = FromHarnessToBrainToolJudgeReq.model_validate(data)
    request = FromHarnessToBrainToolJudgeReq.model_validate(
        {**data, "ram_observations": []} if explicit else data
    )
    gateway = PromptGateway(None)
    text = gateway.render("judge_success", judge_prompt_params(request)).text

    assert request.model_dump(mode="json") == omitted.model_dump(mode="json")
    assert request.model_dump(mode="json")["ram_observations"] == []
    assert "layer" not in type(request).model_fields
    assert text == gateway.render("judge_success", judge_prompt_params(omitted)).text
    assert "最近 RAM 观测" not in text and "（没有检索到相关知识）" not in text
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## 规则", "## 本次输入", "## 目标"]


def test_task_keeps_explicit_observation_but_uses_task_frame() -> None:
    material = params()["task"].model_copy(update={"observation": params()["episode"].observation})
    text = PromptGateway(None).render("judge_success", material).text

    assert "\n## 当前现场\n" in text
    assert "- overlay: none" in text.split("\n## 当前现场\n", 1)[1]


def test_common_rules_share_a_prefix_before_optional_endings() -> None:
    gateway = PromptGateway(None)
    text = {name: gateway.render("judge_success", p).text for name, p in params().items()}
    common = text["episode"].split("\n## 本次输入", 1)[0].rstrip()

    assert text["task"].startswith(common)
    assert text["run"].startswith(common)
    assert "最新规划理由全文" not in common


def test_empty_run_ram_drops_reading_rules_without_losing_other_blocks() -> None:
    material = params()["run"].model_copy(update={"ram_observations": []})
    text = PromptGateway(None).render("judge_success", material).text

    assert "最近 RAM 观测" not in text
    assert "\n## 当前现场\n" in text and "局全文末句。" in text
    assert material.latest_planning.model_dump_json() in text
