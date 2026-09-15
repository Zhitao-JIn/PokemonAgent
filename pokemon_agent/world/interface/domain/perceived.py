"""`Perceived`：world 自己的一次感知产物——观测 + 这次调用产生的账。

原来这份数据装在 `schemas/world/communication/PerceiveOnceResp.py` 里，是
`WorldPort.perceive_once()` 的返回信封。按"模块间零依赖，只靠裸函数和 tool
层交互"这条原则，`WorldPort` 不该再依赖 `schemas.*`——但 `perceive_once()`
确实要一次交出三样东西（观测、模型调用记账、原始帧 PNG），拆成三个返回值
不如一个轻量的、**world 自己拥有**的形状清楚。区别只在于：这不是"world 与
别的模块之间的信封"，产出方和唯一的内部消费方（`tools/game_tools.py`）都
在拿它当"world 吐出来的东西"用，跟 `Facts`/`Observation` 是同一类——
world 自己的数据形状，只是恰好被 tool 层再转手一次，不是"两个模块协商出的
契约"。

`tools/game_tools.py` 把这三个字段原样摊开进
`FromHarnessToGameToolPerceiveOnceResp`（harness ↔ tool 层的信封），
不再嵌套一层 `PerceiveOnceResp`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .observation import Observation


class Perceived(BaseModel):
    """**世界给出的一次感知**：观测 + 这次调用产生的模型调用记录 + 原始帧。

    `calls` 不放进 `Observation`，因为观测是**大脑看的东西**，大脑不该知道
    token 数、延迟这类记账信息。`frame_png` 同理——纯粹是给 trace 落盘、
    供事后复盘用的原始像素。
    """

    observation: Observation = Field(
        description="这一帧的观测。对 reset 是当前帧；对 step 是推进后**链尾那一次感知**的帧"
    )
    calls: list[dict[str, str]] = Field(
        default_factory=list,
        description="这次调用（可能是重试了好几次）产生的每一条模型调用记录，"
        "按发生顺序排列。空列表表示命中缓存，没有产生新调用，**不是 None**",
    )
    frame_png: str = Field(description="这一次感知实际截下来、喂给视觉模型的那张原始 PNG（base64）")
