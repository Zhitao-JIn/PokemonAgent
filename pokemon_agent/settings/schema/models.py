"""`models` 段：每条模型链路的型号、温度、输出上限与单请求超时。

链路名沿用 brain 的四个位置：text（决策 choose）、judge、summary、plan（规划与拆解）。
型号名前缀决定厂商（表在 `brain/providers.py`），这里只存名字。
"""

from typing import Literal

from pydantic import Field

from .base import Section

ThinkingNode = Literal[
    "run.plan",
    "run.judge",
    "run.summarize",
    "episode.decompose",
    "episode.judge",
    "episode.verify",
    "episode.summarize",
    "task.choose",
    "task.judge",
    "task.verify",
    "task.summarize",
]


class ModelLink(Section):
    """一条链路的模型选型。`timeout_s` 是 provider 的单请求 socket 超时。

    `thinking` 默认关闭；需要开思考的位置显式写 `true`。plan 仍保持必填（见
    `PlanModelLink`），其余三个位置可以省略。`cache_marker` 声明静态文字与本次材料的
    分界，None 不设置显式断点；其他厂商的自动缓存不消费这个字段。
    """

    model: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2, allow_inf_nan=False)
    max_tokens: int = Field(gt=0)
    timeout_s: float = Field(gt=0, allow_inf_nan=False)
    thinking: bool = False
    cache_marker: str | None = Field(default=None, min_length=1)


class PlanModelLink(ModelLink):
    """plan 链路的思考开关保持必填；开启后 `timeout_s` 需按量级放宽（经验值 420）。"""

    thinking: bool


class ModelsConfig(Section):
    """四条链路与节点thinking覆盖；后者只覆盖开关，不改变型号及其他超参。"""

    text: ModelLink
    judge: ModelLink
    summary: ModelLink
    plan: PlanModelLink
    json_mode: bool
    node_thinking: dict[ThinkingNode, bool] = Field(default_factory=dict)
    """模型调用节点的独立开关；未配置时继承对应链路，未知节点与非布尔值拒绝。"""
