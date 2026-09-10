"""视觉模型提供方接口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.providers import VisionDescribeReq, VisionDescribeResp

from .llm_provider import LLMProvider


@runtime_checkable
class VisionProvider(Protocol):
    """把「一张或多张图 + 一段提示」变成文本。"""

    def describe(self, req: VisionDescribeReq) -> VisionDescribeResp:
        """把图片交给视觉模型，返回一段描述。

        req：一次视觉补全请求（一组图片 + 要问的问题）。
        前置条件：req.images 非空（至少一张）、req.prompt 非空。
        后置条件：返回的 text 可能是任意字符串（含不合法 JSON），解析由调用方负责。
        失败：底层不可用时抛异常；判定图片未送达时必须抛 ImageNotDelivered，不能静默继续
        （多图时按张数等比放大判定阈值，见 `_MultimodalMixin.describe`）。
        """
        ...


@runtime_checkable
class JudgeProvider(LLMProvider, VisionProvider, Protocol):
    """`judge_llm`/`verify_llm` 现在两种调用都要用得到：带得到图时走
    `describe()`（`VisionProvider`）多模态问一次；一张图都凑不齐时（`StepMemory`
    没留下可用的截图文件名，或文件确实缺失）退化成纯文本，走 `LLMProvider.complete()`
    兜底——两条链路不该因为一张便利副本缺失就直接判定失败。

    不新增方法，纯粹是两个已有 Protocol 的合并——`Brain.__init__` 用这个类型
    标 `judge_llm`/`verify_llm`，一眼能看出"这两个位置的 provider 比 `decide_llm`
    （只标 `LLMProvider`）多担一个职责"。`QwenProvider`（`openai_compatible.py`）
    本来就两个方法都实现，不用改动就满足这个协议。
    """
