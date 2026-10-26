"""Active planning prompts show numeric budgets rather than model-supplied fixed units."""

import json

import pytest

from pokemon_agent.prompt import PromptGateway
from prompt.layout_examples import examples


@pytest.mark.parametrize("task", ["run_plan", "decompose"])
def test_active_planning_example_uses_a_positive_integer_budget(task: str) -> None:
    rendered = PromptGateway(None).render(task, examples()[task])

    line = next(line for line in rendered.text.splitlines() if line.startswith("新增项结构示例："))
    example = json.loads(line.removeprefix("新增项结构示例：").removesuffix("。"))

    assert isinstance(example["budget"], int) and example["budget"] > 0
    assert set(example) == {"goal", "success_criteria", "budget"}
    assert "budget.limit" not in rendered.text.partition("## 本次输入")[0]
