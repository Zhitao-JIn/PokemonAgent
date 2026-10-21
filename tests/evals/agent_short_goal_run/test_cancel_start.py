"""取消购买用例必须真的从尚未扣款的购买确认框开始。"""

import pytest
from _doubles.script_frames import frame

from evals.agent_short_goal_run.dataset import load
from evals.agent_short_goal_run.dataset.build.preconditions import validate_start
from evals.dataset.errors import DatasetError
from pokemon_agent.world import TaskScene
from pokemon_agent.world.interface import DecodedText


@pytest.mark.parametrize(
    "options,valid", [(["YES", "NO"], True), (["BUY", "SELL", "QUIT"], False), ([], False)]
)
def test_cancel_dataset_rejects_main_menu_instead_of_accepting_its_name(options, valid):
    sample = next(s for s in load() if s.check_id == "shop_cancelled")
    observation, ram = frame()
    observation = observation.model_copy(update={"scene": TaskScene.SHOP_ITEMS})
    ram = ram.model_copy(
        update={"decoded": DecodedText(options=options, cursor="", dialog_text="")}
    )

    if valid:
        validate_start(sample, ram, observation)
    else:
        with pytest.raises(DatasetError, match="购买确认"):
            validate_start(sample, ram, observation)
