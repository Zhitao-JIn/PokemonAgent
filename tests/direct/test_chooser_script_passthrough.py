"""chooser normalize：脚本动作原样放行。"""

from __future__ import annotations

from _harness_fixtures.app_config import ACTION_LIMITS, call_policy

from pokemon_agent.brain.interface import Action, ScriptCall
from pokemon_agent.direct.brain_tool import Chooser
from pokemon_agent.prompt import PromptGateway

# ---- 4. chooser normalize：脚本原样放行 ----


def test_normalize_passes_script_through() -> None:
    chooser = Chooser(
        None, policy=call_policy(), action_limits=ACTION_LIMITS, prompt_gateway=PromptGateway(None)
    )  # type: ignore[arg-type] — _normalize 不碰 brain
    action = Action(script=ScriptCall(name="walk_to", args={"x": 5, "y": 2}))
    assert chooser._normalize(action) is action
