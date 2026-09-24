"""文本补全的请求与响应（`LlmCompleteReq` / `LlmCompleteResp`）。

**brain 的内部协议**（0913 深夜十一从 `schemas/providers/` 搬来）：
描述"brain 调一次纯文本模型，问什么、拿回什么"。声明在
`brain/interface/llm_provider.py` 的 `LLMProvider.complete()`，
实现在 `brain/providers.py`，调用点在 `brain/brain.py`——**全在 brain 内**。

**为什么不带 From/To 前缀**：它们是 brain 对外协议面的字段类型，
按 `AGENTS.md` 第十二节第 2 条用裸名（同 `ChooseOnceReq` 那批）。
"""

from __future__ import annotations

from pydantic import BaseModel


class LlmCompleteReq(BaseModel):
    """一次纯文本补全请求。

    **不带图**（0915 129 定案）：带图与否是"这个模型看不看得见图"的判断，
    这个判断归调用方（`Brain` 查 provider 的 `multimodal` 标志）——为真的链路
    直接走 `describe()`（`VisionDescribeReq`），不为图保留一条双格式信封。
    """

    prompt: str
    """完整 prompt 文本。**别删这个字段**——129 收编 images 时曾把整个字段
    一起删掉，Pydantic 对未声明字段默认忽略，`LlmCompleteReq(prompt=…)` 构造
    "成功"但 prompt 静默丢失，直到真机 `req.prompt` 才炸 AttributeError
    （127~129 一路 108 个测试全绿都没拦住：FakeProvider 不摸 `req.prompt`）。
    """

    thinking: bool | None = None
    """这一次请求的思考开关。`None` = 沿用 provider 装配时的设置；`True`/`False` = 只对这一次覆盖。"""


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


__all__ = ["LlmCompleteReq", "LlmCompleteResp"]
