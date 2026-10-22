"""学招结果打字尚未结束时，背景队伍列表不能抢走场合。"""

import pytest

from pokemon_agent.world import ScreenText, TaskScene
from pokemon_agent.world.scene import classify_scene


@pytest.mark.parametrize("dialog", ["Which move sho", "Abandon learni"])
def test_distinctive_learning_prompt_prefix_wins_over_background_party_list(dialog):
    screen = f"   BB?!      :L13\n    HP:[████▎ ] 26/36\n{dialog}"
    text = ScreenText(screen=screen, dialog_text=dialog, strict_dialog=True)

    assert classify_scene(text, bytearray(65536)) is TaskScene.LEARN_MOVE


@pytest.mark.parametrize("dialog", ["Which move is best?", "Abandon the quest?"])
def test_other_dialogue_does_not_become_a_learning_scene(dialog):
    screen = f"   BB?!      :L13\n    HP:[████▎ ] 26/36\n{dialog}"
    text = ScreenText(screen=screen, dialog_text=dialog, strict_dialog=True)

    assert classify_scene(text, bytearray(65536)) is not TaskScene.LEARN_MOVE
