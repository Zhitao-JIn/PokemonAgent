"""LLM 提供方接口：`LLMProvider` + `JudgeProvider`。

**它们的家是 `brain`**（2026-09-13 从 `providers/interface/` 搬来）：`Brain`
是唯一消费这两个协议的地方。放在 `providers/` 时它们是"某个供应商的协议"，
但供应商实现（`QwenProvider` 等）只是恰好都实现了而已——**协议的归属看谁
消费，不看谁实现**。这条路跟 `BrainPort` 走的一样：协议物理上挨着它的实现。

**brain 自己持有带视觉能力的 provider**（0913 定案）：`judge_llm`/`verify_llm`
要能"带得到图时走多模态、凑不齐时退化纯文本"，而 brain 接的
`QwenProvider`/`ArkProvider` 本来就**同时实现 `complete()` 和 `describe()`**
（都继承 `brain/providers.py` 的 `_MultimodalMixin`，那两个类现在也住在
`brain/providers.py`）——这个能力来自 brain **自己持有的实例**，
**不来自 `world`**。所以本模块**不 import `world.interface`**：
`JudgeProvider` 是 brain 自己的协议，描述的是"brain 要的这个位置得两个方法都会"。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.brain.schemas import (
    LlmCompleteReq,
    LlmCompleteResp,
    VisionDescribeReq,
    VisionDescribeResp,
)


@runtime_checkable
class LLMProvider(Protocol):
    """纯文本补全的出口（0915 129 定案：`complete()` 不收图）。

    带图的路由在调用方：实现类会带一个 `multimodal: bool` 实例属性
    （"这个型号看不看得见图"），`Brain` 查它决定走 `describe()`
    （`JudgeProvider` 的方法）还是本协议的 `complete()`——
    本协议不为图保留第二格式，`LlmCompleteReq` 是纯文本信封。
    """

    def complete(self, req: LlmCompleteReq) -> LlmCompleteResp:
        """调用模型，返回一次纯文本补全。

        前置条件：req.prompt 非空。
        后置条件：返回的 text 可能是任意字符串（含不合法 JSON），格式由调用方负责。
        失败：底层不可用时抛异常，不返回空 LlmCompleteResp。
        """
        ...


@runtime_checkable
class JudgeProvider(LLMProvider, Protocol):
    """`judge_llm`/`verify_llm` 两种调用都要用得到：带得到图时走 `describe()`
    多模态问一次；一张图都凑不齐时（`ActMemory` 没留下可用的截图文件名，
    或文件确实缺失）退化成纯文本，走 `LLMProvider.complete()` 兜底——
    两条链路不该因为一张便利副本缺失就直接判定失败。

    **它是 brain 自己的协议，不是跨模块合并**（0913 修正）：早先的写法是
    `class JudgeProvider(LLMProvider, VisionProvider, Protocol)`，借 `world`
    的 `VisionProvider` 来表达"还会 `describe()`"。那是**用别人的协议名描述
    自己的能力**——brain 的 provider 从来不是 world 那个协议的实现者，
    它只是恰好也长着 `describe()` 这个方法。现在 `describe()` 由本模块
    自己声明（形参与返回类型用 `brain/schemas/` 那对补全信封——**0913
    深夜十一起它是 brain 的内部协议**，world 另有一份自己的副本，
    两份同构是刻意的，见 `brain/schemas/__init__.py`）。

    `Brain.__init__` 用这个类型标 `judge_llm`/`verify_llm`，一眼能看出
    "这两个位置的 provider 比 `decide_llm`（只标 `LLMProvider`，带图与否由
    其 `multimodal` 标志决定，`choose()` 查表分派——0915 129）
    多担一个职责"。`QwenProvider`/`ArkProvider` 本来就两个方法都实现，
    不用改动就满足这个协议。
    """

    def describe(self, req: VisionDescribeReq) -> VisionDescribeResp:
        """把图片交给视觉模型，返回一段描述。

        req：一次视觉补全请求（一组图片 + 要问的问题）。
        前置条件：req.images 非空（至少一张）、req.prompt 非空。
        后置条件：返回的 text 可能是任意字符串（含不合法 JSON），解析由调用方负责。
        失败：底层不可用时抛异常；判定图片未送达时必须抛 `ImageNotDelivered`。
        """
        ...


__all__ = ["JudgeProvider", "LLMProvider"]
