"""单能力脑评测的装配：只造被测那一条链路，型号由评测参数覆盖，其余全取保底配置。"""

from __future__ import annotations

from typing import Literal

from pokemon_agent.direct.brain_tool import BrainTool
from pokemon_agent.settings import load_config


def single_link_brain(link: Literal["text", "judge", "summary", "plan"], model: str) -> BrainTool:
    """按保底配置造只含 `link` 的 `BrainTool`，该链路型号换成 `model`。"""
    app = load_config().config
    chosen = getattr(app.models, link).model_copy(update={"model": model})
    return BrainTool.build(
        links=(link,),
        models=app.models.model_copy(update={link: chosen}),
        retry=app.retry,
        request_timeouts=app.request_timeouts_s,
        action_limits=app.action_limits,
        image_cap=app.memory.scope_image_cap,
    )


__all__ = ["single_link_brain"]
