"""视觉补全的请求与响应（`VisionDescribeReq` / `VisionDescribeResp`）。

**brain 的内部协议**（0913 深夜十一从 `schemas/providers/` 搬来）：
描述"brain 调一次视觉模型，喂几张图 + 一个问题、拿回一段描述"。
声明在 `brain/interface/llm_provider.py` 的 `JudgeProvider.describe()`
（judge/verify 带得到图时走它），实现在 `brain/providers.py` 的
`_MultimodalMixin.describe()`。

**world 有一份自己的副本**：`world/interface/domain/vision_describe.py`——
world 的 `VisionProvider` 协议也要声明这两个形状，但它**不 import brain**。
两份字段同构是刻意的：brain 的实现同时满足两个协议，装配点递进去时结构对得上。
理由与代价见 `brain/schemas/__init__.py` 的模块 docstring。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisionDescribeReq(BaseModel):
    """一次视觉补全的请求：一张或多张图加上要问的问题。

    images：待识别的图片，**完整的 PNG data URI 字符串**（不是原始字节）——
        `data:image/png;base64,…`，0915 起这是**唯一**格式（自描述、grep 可寻，
        裸 base64 已废；产出点唯一：`world/pyboy_world._png_data_uri`）。
        **按要出现在 prompt 里的顺序排列**，至少一张。`ActMemory`
        直接存 data URI（省掉“存文件名→用的时候再读盘+编码”这一趟），
        `judge`/`verify_steps` 用的图片天然就是已经编好的字符串，
        这里用 `str` 才不用来回编解码。
    prompt：要问这些图的问题。
    """

    images: list[str] = Field(min_length=1)
    prompt: str


class VisionDescribeResp(BaseModel):
    """一次视觉补全的结果。

    `input_tokens` 不是可选的记账信息，**它是正确性的证据**：
    网关静默丢弃图片时，这个数会塌回纯文本的量级。见
    `brain/providers.py::_MultimodalMixin.describe()` 的 floor 校验。
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    """同 `LlmCompleteResp.cached_tokens`——`input_tokens` 里命中隐式
    缓存的部分。多模态请求命中率天然更低：图片这一段每次都不同（不同帧），
    只有跟在图片后面的静态文字段有机会被复用，且要看服务端是不是从请求
    最开头匹配前缀（见 `docs/ROADMAP.md`"缓存命中率怎么统计"一条）。
    """
    reasoning_tokens: int = 0
    """同 `LlmCompleteResp.reasoning_tokens`——判定链路（judge/verify）
    带图问思考模型时，输出的大头往往是思考 token 而不是结论本身。"""


__all__ = ["VisionDescribeReq", "VisionDescribeResp"]
