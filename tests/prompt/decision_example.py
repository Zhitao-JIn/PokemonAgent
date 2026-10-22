"""从 harness 请求显式转换并渲染活动决策版本。"""

from pokemon_agent.direct.brain_tool import decide_prompt_params
from pokemon_agent.prompt import PromptGateway
from pokemon_agent.schemas.harness import FromHarnessToBrainToolChooseOnceReq


def build_prompt(req: FromHarnessToBrainToolChooseOnceReq, *, max_segments: int) -> str:
    """调用方提供非空目标、动作空间与正的段数上限。"""
    return (
        PromptGateway(None)
        .render("decide_action", decide_prompt_params(req, max_segments=max_segments))
        .text
    )
