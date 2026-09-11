"""一次模型调用留下的账，外加它成没成。

原来放在 `schemas/providers/domain/model_call.py`；跟 `LLMProvider`/
`VisionProvider` 这些协议一样，是 `providers/` 这个模块自己的数据形状，
不是"给别人看的跨层契约"，挪到这里同住一包。`schemas/providers/__init__.py`
不再 re-export 它——需要的地方直接 `from pokemon_agent.providers import
ModelCall`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelCall(BaseModel):
    """一次模型调用留下的账，外加它成没成。

    ## 为什么大脑要把账"交出来"而不是自己记

    **只有 Harness 写 trace。** 大脑是被调用方：它返回结果和账单，
    由 Harness 翻译成事件。规则只有一句：**谁控制循环，谁记账。**
    判定器碰不到自己的账是所有大脑调用的共同处境。

    `payload` 直接就是 trace 里 `MODEL_CALL` 的内容。`error_kind` 非空时
    Harness 会**另外补一条 `ERROR` 事件**——账单和失败模式是两件事：
    前者回答"花了多少钱"，后者回答"为什么没拿到东西"，混在一条里两个都统计不出来。
    """

    payload: dict[str, str] = Field(
        default_factory=dict,
        description="token、延迟、第几次尝试、原始输出（`raw`）、实际发给模型的文本输入"
        "（`prompt`，方便观测台/复盘直接看这次调用问了什么，不用去翻拼装代码）。"
        "**失败的调用也要有**——它同样烧了钱，而 `raw`/`prompt` 让你改进解析器之后能离线"
        "重算，不必再花 token 重跑",
    )
    error_kind: str = Field(
        default="",
        description="失败类型（ParseFailure / IllegalAction / OutputTruncated…）。"
        "空串表示这次成功了。**单独一列**：聚合失败模式时不必去解析 error 字符串",
    )
    error: str = Field(default="", description="失败详情，一句话")
