"""共享蒸馏输出与附图读法通过公开网关验证三层参数化。"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel

from pokemon_agent.prompt import DistillOutputParams, ImageReadingParams, PromptGateway

from .unit_fixtures import ExampleParams, make_unit

Compose = Callable[[str, BaseModel], str]
FIELDS = {
    "summary",
    "reason",
    "reusable_patterns",
    "critical_decisions",
    "failure_points",
    "quality_score",
    "quality_rationale",
    "applicable_scenes",
    "tags",
    "markdown",
}


@pytest.fixture(scope="module")
def compose(tmp_path_factory: pytest.TempPathFactory) -> Compose:
    root = tmp_path_factory.mktemp("distillation_fragments")
    source = Path(__file__).resolve().parents[2] / "pokemon_agent/prompt/registry.json"
    data = json.loads(source.read_bytes())
    for name, contract in (
        ("distill_output", "DistillOutputParams"),
        ("image_reading", "ImageReadingParams"),
    ):
        wrapper = f"example_{name}"
        body = (
            f"from pokemon_agent.prompt import {contract}\nimport json\n"
            f'return json.dumps(compose("{name}", {contract}.model_validate_json(params.value)))'
        )
        make_unit(root, wrapper, body=body)
        data["tasks"][wrapper] = {"active": "v1"}
    path = root / "registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    gateway = PromptGateway(path)

    def render(name: str, params: BaseModel) -> str:
        return json.loads(
            gateway.render(f"example_{name}", ExampleParams(value=params.model_dump_json())).text
        )

    return render


@pytest.mark.parametrize(
    "scope,points", [("task", "三至五"), ("episode", "二至四"), ("run", "短要点")]
)
def test_output_fields_and_compact_rules_preserve_all_three_contracts(
    scope: str, points: str, compose: Compose
) -> None:
    text = compose("distill_output", DistillOutputParams(scope=scope))
    example = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])

    assert set(example) == FIELDS and example["summary"] and example["markdown"]
    assert points in text and "全部必填" in text
    assert "quality_score 是 0.0–1.0 的浮点数" in text
    assert "applicable_scenes 只填写实际适用的稳定标签" in text
    assert "来源章与记录不一致时保留差异" in text
    assert "未经验证的解释标为不确定" in text and "JSON 字符串里的换行使用转义" in text
    assert "负样本" in text and "对象身份" in text and "参照时刻" in text


@pytest.mark.parametrize(
    "scope,origin", [("task", "逐键记录"), ("episode", "各 task"), ("run", "各局")]
)
def test_image_reading_preserves_grid_order_and_each_layers_actual_source(
    scope: str, origin: str, compose: Compose
) -> None:
    text = compose("image_reading", ImageReadingParams(scope=scope))

    assert origin in text and "按时间先后" in text and "最后一张最新" in text
    assert "3 列网格图" in text and "帧间黑线分隔" in text
    assert "按行优先、从左到右从上到下" in text
    assert "以截图上能直接看到的内容为准" in text and "不拿图重新推算位置或坐标" in text
    assert ("超过数量上限时丢弃最旧的帧" in text) == (scope == "run")
    assert "去重" in text
