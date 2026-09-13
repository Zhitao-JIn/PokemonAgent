"""world 自己的视觉补全信封：`VisionDescribeReq` / `VisionDescribeResp`。

**为什么 world 要有一份自己的**（0913 深夜十一，用户裁定）：
world 的 `VisionProvider` 协议（`world/interface/vision_provider.py`）声明
`describe(req) -> resp`，它必须能说出这两个形状。而这两个形状的另一份在
`brain/schemas/vision.py`——**实现（brain 的 `_MultimodalMixin`）同时满足
brain 的 `JudgeProvider` 与 world 的 `VisionProvider` 两个协议**。

此前只有顶层 `schemas/providers/` 那一份，两个模块都 import 它。但那是
"内部协议住在外层"——用户把它收进 brain 之后，world 若跟着 import
`brain.schemas`，就成了一条 `world → brain` 的横向依赖，两个模块都不能独立拷走。

**所以复制一份**：world 这一份**只复制它用得到的两个类**（brain 需要四个，
它还要 `LlmComplete*`）。两份字段同构是**刻意的、必须保持的**——
装配点把一个 brain 实现（`QwenProvider`）当 `VisionProvider` 递给
`PyBoyWorld` 时，`PyBoyWorld` 构造的是**本文件的** `VisionDescribeReq`，
而实现读的是 **brain 那份**的字段名；两边字段一旦漂移，运行时就炸。

**这个"同构"靠什么守**：不是靠 import 同一个类（那样就把依赖加回来了），
而是靠**两边都从同一份原始定义复制、且字段名出现在同一处核对**——
`tools/` 是唯一的桥，谁改字段谁负责两边一起改（`AGENTS.md` 第十二节
"跨包引用登记"里记了这一条）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisionDescribeReq(BaseModel):
    """一次视觉补全的请求：一张或多张图加上要问的问题。

    **字段必须与 `brain/schemas/vision.py::VisionDescribeReq` 保持同构**
    （`images: list[str]` + `prompt: str`）——实现同时服务两个协议，
    字段漂移就是运行时错误。

    images：待识别的图片，**base64 编码后的 PNG 字符串**（不是原始字节）——
        直接是 REST API `image_url` 那个字段要拼的内容
        （`f"data:image/png;base64,{img}"`），**按要出现在 prompt 里的顺序
        排列**，至少一张。`PyBoyWorld` 产出的是原始字节，构造这个请求之前
        自己 `base64.b64encode(...).decode()` 一次。
    prompt：要问这些图的问题。
    """

    images: list[str] = Field(min_length=1)
    prompt: str


class VisionDescribeResp(BaseModel):
    """一次视觉补全的结果。

    **字段必须与 `brain/schemas/vision.py::VisionDescribeResp` 保持同构**。

    `input_tokens` 不是可选的记账信息，**它是正确性的证据**：
    网关静默丢弃图片时，这个数会塌回纯文本的量级——实现（brain 那份）
    据此抛 `ImageNotDelivered`，本模块在 `pyboy_world.py` 里把它收编成
    `PerceptionAttemptFailed`。
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


__all__ = ["VisionDescribeReq", "VisionDescribeResp"]
