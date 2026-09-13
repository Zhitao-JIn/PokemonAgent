"""`ModelCall`：**brain 方言里的**一次模型调用账。

## 为什么 brain 有自己的一份

`brain` 是第三方模块的视角（铁律 2）：它不认识 tool 层，也不认识 harness。
"这次调用花了多少 token、为什么没成"是 brain 必须交出来的东西——但它交出来的
**是自己方言里的形状**，跟别人怎么用无关。此前这个类寄居在
`providers/interface/`，导致 brain 方言里出现了一个"别人的类型"（spec
§9.2 记着这条欠账："把它收进 brain 是单独一轮的事"）——这一轮就是那一轮。

tool 层的 `ModelCall`（`pokemon_agent.tools.interface.ModelCall`，实体在
`schemas/harness/communication/ModelCall.py`）是**另一个类**：它多一个
`with_attempt()`（循环控制者盖章用），是 tool 层攒账、搬运时用的工作形状。
两者字段此刻恰好一样，但**语义归属不同**：

| | brain 的这一份 | tool 层的那一份 |
|---|---|---|
| 谁产出 | `Brain` 六个方法 | `BrainTool` 的循环 / `world` 的裸 dict |
| 谁消费 | `BrainTool`（转成自己那份） | `trace` 渲染层（摊平成 payload） |
| 有 `with_attempt()` 吗 | 没有——盖章不是大脑的事 | 有 |

**为什么不共用同一个类**：共用意味着 `brain` 要 import `tools.interface`，
一条横向依赖（`brain → tools`），而铁律 2 规定依赖方向只有
`brain → interfaces ← harness`。字段相同不代表类型相同——语义边界比代码
重复更值钱，而重复只有三个字段。

**`attempt` 字段不由大脑盖**：它属于"这是第几次尝试"，只有循环控制者知道。
brain 交出来的账里没有这一项；`BrainTool` 在收进重试账那一刻统一盖上
（`ModelCall.with_attempt()` 往 `payload["attempt"]` 里写，不是顶层字段）。

## 为什么大脑要把账"交出来"而不是自己记

**只有 Harness 写 trace。** 大脑是被调用方：它返回结果和账单，
由 Harness 翻译成事件。规则只有一句：**谁控制循环，谁记账。**
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelCall(BaseModel):
    """brain 一次模型调用留下的账，外加它成没成。

    **不可变值语义**（Pydantic 模型，改动一律用 `model_copy`）——
    重试循环里每一条账都要独立留档。
    """

    payload: dict[str, str] = Field(
        default_factory=dict,
        description="token、原始输出（`raw`）、实际发给模型的文本输入（`prompt`）。"
        "**失败的调用也要有**——它同样烧了钱，而 `raw`/`prompt` 让你改进解析器"
        "之后能离线重算，不必再花 token 重跑",
    )
    error_kind: str = Field(
        default="",
        description="失败类型（ParseFailure / IllegalAction / OutputTruncated…）。"
        "空串表示这次成功了。**单独一列**：聚合失败模式时不必去解析 error 字符串",
    )
    error: str = Field(default="", description="失败详情，一句话")


__all__ = ["ModelCall"]
