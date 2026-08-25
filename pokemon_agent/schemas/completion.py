"""模型调用的返回值：文本模型的 `Completion`、视觉模型的 `VisionCompletion`。

## 为什么在 `schemas/` 而不是 `interfaces/`

目录分工是 `schemas/` 放 Pydantic 数据模型、`interfaces/` 放 Protocol 定义
（CLAUDE.md 第四节）。这两个类原本长在 `interfaces/llm.py` 和 `interfaces/vision.py`
里——就在用到它们的 Protocol 旁边，读起来顺，但那让 `interfaces/` 同时承担了两件事。
代价不是洁癖：接口先行那条规矩说「光读 `interfaces/` 就能看懂整个系统怎么运转」，
而数据模型混在里面，读的人分不清哪些是**契约**、哪些是**契约里流的东西**。

## 为什么两个放同一个文件

它们回答的是同一个问题——「一次模型调用回来了什么」——而且**都带着一个
不是记账、而是正确性证据的字段**（`truncated` / `input_tokens`，见各自的说明）。
这个共同点是本项目踩出来的，分成两个文件就没地方写它。

## 为什么不是两个各自 `total_tokens` 的通用类

字段名故意不统一：文本那边是 `prompt_tokens`/`completion_tokens`，视觉那边是
`input_tokens`/`output_tokens`，跟各自网关返回的名字走。中间再翻译一层，
排查"网关到底报了什么"时就得反查映射表。
"""

from __future__ import annotations

from pydantic import BaseModel


class Completion(BaseModel):
    """一次文本补全的结果。

    把 token 数放进返回值而不是让调用方去查，是为了成本统计能在**调用点**就地产出 trace，
    不需要 LLM 实现和成本模块互相认识。
    """

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    truncated: bool = False
    """输出是不是被 max_tokens 截断了。

    **必须由 provider 给，不能让调用方猜。** 调用方不知道 max_tokens 是多少，
    只能拿 `completion_tokens == 某个整数` 去猜，那是巧合不是判据。

    为什么值得单开一个字段：截断在下游表现为"JSON 少了个右括号"，
    和"模型不会写 JSON"长得一模一样，但**修法完全相反**——
    前者要调大 max_tokens 或让模型少说，后者要改 prompt 或上约束解码。
    混成一类 ParseFailure，统计里就永远看不见它。
    """


class VisionCompletion(BaseModel):
    """一次视觉补全的结果。

    `input_tokens` 不是可选的记账信息，**它是正确性的证据**：
    网关静默丢弃图片时，这个数会塌回纯文本的量级。见 `VisionProvider.describe` 的说明。
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
