"""节点开关覆盖链路默认值，拼错节点或布尔类型时在装配前拒绝。"""

import json

import pytest
from pydantic import ValidationError

from pokemon_agent.settings import ModelsConfig, load_config


def test_node_thinking_is_optional_and_can_override_both_directions() -> None:
    data = load_config().config.models.model_dump(mode="json")
    data["node_thinking"] = {"task.verify": True, "run.plan": False}

    models = ModelsConfig.model_validate_json(json.dumps(data))

    assert models.node_thinking == {"task.verify": True, "run.plan": False}
    assert models.summary.thinking is False
    assert models.plan.thinking is True


@pytest.mark.parametrize("overrides", [{"task.verfy": False}, {"task.verify": "false"}])
def test_invalid_node_configuration_is_rejected(overrides: dict[str, object]) -> None:
    data = load_config().config.models.model_dump(mode="json")
    data["node_thinking"] = overrides

    with pytest.raises(ValidationError):
        ModelsConfig.model_validate_json(json.dumps(data))
