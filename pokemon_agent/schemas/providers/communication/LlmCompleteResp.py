"""文本模型补全的返回值。"""

from __future__ import annotations

from pydantic import BaseModel


class LlmCompleteResp(BaseModel):
    """一次文本补全的结果。

    把 token 数放进返回值而不是让调用方去查，是为了成本统计能在**调用点**就地产出 trace，
    不需要 LLM 实现和成本模块互相认识。
    """

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    """`prompt_tokens` 里有多少命中了供应商的隐式缓存——
    DashScope/火山方舟都默认开、不可关，命中的部分只按标准输入价的 20%
    计费。取不到就是 0，不代表没命中，也可能是响应里根本没带这个字段。
    """
    reasoning_tokens: int = 0
    """`completion_tokens` 里有多少是思考（reasoning）token——思考模型
    （doubao-seed-2.x 等）把推理也算进 completion 且**不受 max_tokens 约束**
    （0907 实测：max_tokens=8、reasoning 跑到 1.9k），不单列的话"输出很省"
    的账是假的。读 `usage.completion_tokens_details.reasoning_tokens`，
    非思考模型/老响应没有这个字段，取 0。"""
    truncated: bool = False
    """输出是不是被 max_tokens 截断了。

    **必须由 provider 给，不能让调用方猜。** 调用方不知道 max_tokens 是多少，
    只能拿 `completion_tokens == 某个整数` 去猜，那是巧合不是判据。

    为什么值得单开一个字段：截断在下游表现为"JSON 少了个右括号"，
    和"模型不会写 JSON"长得一模一样，但**修法完全相反**——
    前者要调大 max_tokens 或让模型少说，后者要改 prompt 或上约束解码。
    混成一类 ParseFailure，统计里就永远看不见它。
    """
