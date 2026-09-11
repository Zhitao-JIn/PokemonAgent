"""视觉端口 describe() 的结果。"""

from __future__ import annotations

from pydantic import BaseModel


class VisionDescribeResp(BaseModel):
    """一次视觉补全的结果。

    `input_tokens` 不是可选的记账信息，**它是正确性的证据**：
    网关静默丢弃图片时，这个数会塌回纯文本的量级。见 `VisionProvider.describe` 的说明。
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
