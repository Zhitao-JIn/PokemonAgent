"""`CallPolicy`：tool 层一条模型链路的调用策略——重试预算、单请求时限、图片帽。

由 `BrainTool.build()` 按配置文件的 `retry` / `request_timeouts_s` / `memory` 三段组装，
每个能力对象（`Planner` / `Chooser` / …）构造时**必传**，类里不留任何默认数字。
"""

from __future__ import annotations

from dataclasses import dataclass

from pokemon_agent.settings import RetryConfig


@dataclass(frozen=True)
class CallPolicy:
    """一条链路的调用策略。

    `retry`：重试预算与退避；`request_timeout_s`：这条链路单次请求的总时限（秒）；
    `image_cap`：喂给模型的历史图片上限（保留最新的）。
    `thinking_node`与`thinking`：逻辑调用节点及装配后默认开关，供每次trace记账。
    """

    retry: RetryConfig
    request_timeout_s: float
    image_cap: int
    thinking_node: str | None = None
    thinking: bool | None = None
    """节点及装配后的生效默认值；未提供时保留旧调用方的无节点语义。"""


__all__ = ["CallPolicy"]
