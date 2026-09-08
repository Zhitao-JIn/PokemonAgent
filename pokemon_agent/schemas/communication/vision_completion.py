"""视觉补全的一对协议：请求（`VisionCompletionReq`）与结果（`VisionCompletionResp`）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisionCompletionReq(BaseModel):
    """一次视觉补全的请求：一张或多张图加上要问的问题。

    images：待识别的图片，**base64 编码后的 PNG 字符串**（不是原始字节）——
        直接是 REST API `image_url` 那个字段要拼的内容
        （`f"data:image/png;base64,{img}"`），**按要出现在 prompt 里的顺序
        排列**，至少一张。`StepMemory`
        直接存 base64（省掉“存文件名→用的时候再读盘+编码”这一趟），
        `judge`/`verify_steps` 用的图片天然就是已经编好的字符串，
        这里用 `str` 才不用来回编解码；感知（`PyBoyWorld`）产出的是
        原始字节，调用方在构造这个请求之前自己 `base64.b64encode(...).decode()`
        一次。
    prompt：要问这些图的问题。
    """

    images: list[str] = Field(min_length=1)
    prompt: str


class VisionCompletionResp(BaseModel):
    """一次视觉补全的结果。

    `input_tokens` 不是可选的记账信息，**它是正确性的证据**：
    网关静默丢弃图片时，这个数会塌回纯文本的量级。见 `VisionProvider.describe` 的说明。
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    """同 `TextCompletionResp.cached_tokens`——`input_tokens` 里命中隐式
    缓存的部分。多模态请求命中率天然更低：图片这一段每次都不同（不同帧），
    只有跟在图片后面的静态文字段有机会被复用，且要看服务端是不是从请求
    最开头匹配前缀（见 `docs/ROADMAP.md`"缓存命中率怎么统计"一条）。
    """
    reasoning_tokens: int = 0
    """同 `TextCompletionResp.reasoning_tokens`——判定链路（judge/verify）
    带图问思考模型时，输出的大头往往是思考 token 而不是结论本身。"""
