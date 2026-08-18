"""视觉提供方接口 —— 感知链路的模型出口。

**为什么不并进 `LLMProvider`**，四条理由，任何一条单独都够：

1. **大脑不该有看图的能力。** `Observation` 的 docstring 写死了"原始画面不进这里"。
   `LLMProvider` 一旦长出图片参数，大脑手里就多了一个它不该有的口子。
2. **两条链路会选不同的模型。** 感知每步都调、任务简单（枚举内分类 + 按 schema 填字段），
   该用最便宜的档；决策要真推理。分成两个 Port 才能分别选型、分别换供应商。
3. **本项目自己定过这条规矩。** `LLMProvider` 的 docstring：
   "真上约束解码时应当加一个**新方法**而不是改这个方法的语义。" 加图片是同类情况，且更重。
4. **计费结构就是这么分的。** 决策走有资源包的文本模型，感知走带免费额度的廉价视觉模型。

和 `LLMProvider` 一样做得很薄：只负责"图片进、文本出"。
**分类、schema 填充、类型判定都不在这里**——那些是感知层的事，换模型不该动它们。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class VisionCompletion(BaseModel):
    """一次视觉补全的结果。

    `input_tokens` 不是可选的记账信息，**它是正确性的证据**：
    网关静默丢弃图片时，这个数会塌回纯文本的量级。见 `VisionProvider.describe` 的说明。
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class VisionProvider(Protocol):
    """把「一张图 + 一段提示」变成文本。"""

    def describe(self, image_png: bytes, prompt: str) -> VisionCompletion:
        """对图片做一次视觉补全。

        前置条件：image_png 非空、prompt 非空。
        后置条件：返回的 text 可能是任意字符串（**包括不合法的 JSON**）——
            解析是调用方的事，本方法不为格式负责，与 `LLMProvider.complete` 一致。

        失败：底层不可用时抛异常，不返回空结果。

        ⚠️ **实现方必须校验图片确实被消费了。**

        实测：DashScope 的 Anthropic 兼容端点会**接受**带图请求、**不报任何错**、
        返回一段读起来完全合理的描述——而图根本没传到模型，描述全是凭空编的。
        判据是 token 数不是回答内容：一张 2.4KB 的 PNG 真被处理时输入至少几百 token，
        实测却只比纯文本多了提示词的那十几个。

        这是最危险的一类失败：不报错，只幻觉。不校验就会得到一个"完全正常工作"
        的 agent，每一步观测都是假的，等基线实验和 A/B 跑完才发现全部作废。

        校验形式由实现方定（token 下界是最便宜的一种），
        但**判定为未送达时必须抛 `ImageNotDelivered`，不能静默继续**。
        """
        ...
