"""视觉模型提供方接口：`VisionProvider`。

**它的家是 `world`**（2026-09-13 从 `providers/interface/` 搬来）：`world` 是
唯一真正调 `describe()` 的模块（`pyboy_world.py` 拿它读一帧画面），"把图片变成
文字"就是 world 这个子系统对外要的那个能力。放在 `providers/` 时它是"某个
供应商协议"，但供应商实现（`QwenProvider` 等）只是恰好两个方法都实现了而已
——协议的归属看**谁消费**，不看谁实现。

`JudgeProvider`（brain 自己那份"会 `describe()` 的 LLM"）**不在 `world` 的
谱系里**，住在 `brain/interface/llm_provider.py`——brain 有自己的实例
（`brain/providers.py` 的 `QwenProvider`/`ArkProvider` 都继承 `_MultimodalMixin`，
`complete()` 与 `describe()` 同在一个类里），**不借 `world` 的任何东西**。两个协议
长得像，只是因为它们描述的是同一个物理能力；对 world 而言 `describe()` 是"看画面"，
对 brain 而言是"判定时带图"。**同形不同约，各自声明自己的。**

**实现住 `brain/providers.py`，这不构成 `world → brain` 依赖**：本模块只声明
协议（零 import），`PyBoyWorld` 拿到的那个实例是 tool 层的接线工厂
（`tools/vision_factory.build_vision_provider()`）造出来、由装配点
（`build.py::build_real()`）递进去的——`world` 自己一行都没提过 brain。
`describe()` 出错时的**任何异常都由 world 就地收编**：`PyBoyWorld.perceive_once()`
先放行自己的 `PerceptionAttemptFailed`，其余一律包成它——所以本协议**不声明**
`ImageNotDelivered`（那是 brain 的词汇，见 `brain/errors.py`），
world 侧只认"这次没读出来"这个处境。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain.vision_describe import VisionDescribeReq, VisionDescribeResp


@runtime_checkable
class VisionProvider(Protocol):
    """把「一张或多张图 + 一段提示」变成文本。"""

    def describe(self, req: VisionDescribeReq) -> VisionDescribeResp:
        """把图片交给视觉模型，返回一段描述。

        req：一次视觉补全请求（一组图片 + 要问的问题）。
        前置条件：req.images 非空（至少一张）、req.prompt 非空。
        后置条件：返回的 text 可能是任意字符串（含不合法 JSON），解析由调用方负责。
        失败：底层不可用时抛异常；判定图片未送达时必须抛自己的异常
        （brain 的实现抛 `ImageNotDelivered`，world 在 `perceive_once` 里就地
        收编成 `PerceptionAttemptFailed`），不能静默继续
        （多图时按张数等比放大判定阈值，见 `_MultimodalMixin.describe`）。
        """
        ...


__all__ = ["VisionProvider"]
