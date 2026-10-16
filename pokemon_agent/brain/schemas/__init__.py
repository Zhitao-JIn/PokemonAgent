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

文本与图片补全均使用 brain 自己声明的请求/响应形状，模块可独立替换。

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
