"""brain 自己的补全信封：`LlmComplete*` + `VisionDescribe*`。

**为什么它们住 brain**（0913 深夜十一，用户裁定）：0913 早些时候把
`providers/` 实现整包搬进 brain 之后，**这四个信封就成了 brain 的内部协议**——
它们描述的是"brain 调一次模型，请求长什么样、响应带什么回来"，
实现（`brain/providers.py`）与声明（`brain/interface/llm_provider.py`）
都在 brain 里。它们此前住 `pokemon_agent/schemas/providers/`，那是
"brain 还没独占这套协议"时的残留：**内部协议不该在外层。**

**brain 拷走要能独立跑**：这四个类搬进来之后，`brain/` 对
`pokemon_agent.schemas.*` 的依赖**只剩数据形状**（那些是跨层信封的字段类型，
本来就该共享）。补全协议不再欠外部任何东西。

**world 怎么办**：world 的 `VisionProvider` 协议也要声明 `describe()` 的
请求/响应形状。它**不 import brain**——world 在自己的
`world/interface/domain/vision_describe.py` 里**复制一份**
（只复制它需要的两个：`VisionDescribeReq`/`VisionDescribeResp`）。
两份字段同构是**刻意的**：实现（brain 的 `_MultimodalMixin`）同时满足两个协议，
装配点递进去时结构对得上即可——**同形不同约，各自声明自己的**
（跟 `JudgeProvider` 与 `VisionProvider` 长得像但分属两家的道理一样）。

**放这里的代价与收益**：代价是"同一个形状有两个副本"（brain 一份、world 一份），
收益是**两个模块都能独立拷走**。用户拍板取后者——"我要的是 brain 可以作为
第三方替换"。

**目录内部结构**：扁平放，不分子目录。两个文件分别装一对 Req/Resp，
外加 `__init__.py` 做统一出口。
"""

from .completion import LlmCompleteReq, LlmCompleteResp
from .vision import VisionDescribeReq, VisionDescribeResp

__all__ = [
    "LlmCompleteReq",
    "LlmCompleteResp",
    "VisionDescribeReq",
    "VisionDescribeResp",
]
