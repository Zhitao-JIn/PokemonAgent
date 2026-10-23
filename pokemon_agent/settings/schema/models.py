"""`models` 段：每条模型链路的型号、温度、输出上限与单请求超时。

链路名沿用 brain 的四个位置：text（决策 choose）、judge、verify、plan（规划与拆解）。
型号名前缀决定厂商（表在 `brain/providers.py`），这里只存名字。
"""

from pydantic import Field

from .base import Section


class ModelLink(Section):
    """一条链路的模型选型。`timeout_s` 是 provider 的单请求 socket 超时。

    `thinking` 默认关闭；需要开思考的位置显式写 `true`。plan 仍保持必填（见
    `PlanModelLink`），其余三个位置可以省略。
    """

    model: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2, allow_inf_nan=False)
    max_tokens: int = Field(gt=0)
    timeout_s: float = Field(gt=0, allow_inf_nan=False)
    thinking: bool = False


class PlanModelLink(ModelLink):
    """plan 链路的思考开关保持必填；开启后 `timeout_s` 需按量级放宽（经验值 420）。"""

    thinking: bool


class ModelsConfig(Section):
    """四条链路 + 统一的 JSON 输出开关（请求体带 `response_format: json_object`）。"""

    text: ModelLink
    judge: ModelLink
    verify: ModelLink
    plan: PlanModelLink
    json_mode: bool
