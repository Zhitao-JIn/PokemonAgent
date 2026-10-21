"""购买数量框不在底部对话字段中，须核对同帧真实整屏解码。"""

import pytest

from evals.agent_short_goal_run.scorer import judge
from pokemon_agent.world import TaskScene
from tests.evals.agent_short_goal_run.test_evals_checks import frame, sample, stream


def quantity_frame(
    scene=TaskScene.SHOP_ITEMS, screen="┌───────────┐\n│×01    ¥200│\n└───────────┘"
):
    event = frame(2, dialog="Take your time.")
    facts = event.content.facts.model_copy(update={"screen": screen})
    content = event.content.model_copy(update={"facts": facts, "scene": scene})
    return event.model_copy(update={"content": content})


def test_shop_quantity_and_price_box_is_a_valid_item_selection_result():
    result = judge(stream(frame(1), quantity_frame()), sample("shop_item_selected"))

    assert result.outcome == "pass"
    assert result.evidence == ["u2"]


@pytest.mark.parametrize(
    "event",
    [
        quantity_frame(scene=TaskScene.BAG),
        quantity_frame(screen="POKé BALL ×01 ¥200"),
        quantity_frame(screen="┌───────────┐\n│POKé BALL  │\n└───────────┘"),
    ],
)
def test_a_bag_count_or_an_unrelated_box_is_not_a_purchase_confirmation(event):
    assert judge(stream(frame(1), event), sample("shop_item_selected")).outcome == "fail"
