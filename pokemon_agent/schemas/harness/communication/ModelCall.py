"""`ModelCall`：一次模型调用留下的账，外加它成没成。

## 它为什么住在这里（曾经两度搬家）

| 时间 | 住址 | 理由 / 问题 |
|---|---|---|
| 最初 | `schemas/providers/domain/` | 当时 `providers` 还有自己的 schemas 子包 |
| 2026-09-12 | `providers/interface/domain/` | "它是 providers 的"——但**五个协议从不返回它** |
| 2026-09-13 | **这里** | `schemas/harness` 才是"harness 唯一认识的那一层" |

**为什么最终落在这里**——它跟 `ModelCallLog`（本文件下方，`list[ModelCall]`
的别名）是同一批读者：`harness` 侧（`think_action`/`judge`/`verify_and_summarize`/
`harness/sensing.perceive_once`）拿到账之后要**原样装进 `FromHarnessToTraceToolAppendReq.calls`**
交给 trace 渲染，而这个信封是 `schemas.harness` 的类型。**装得进去的前提是同一个类型**。

试过放 `tools.interface`（它看起来更像"账的家"），立刻回环：
`tools/interface/ports.py` 要 `from pokemon_agent.schemas.harness import …`，
而 `schemas.harness` 的信封要 `ModelCall`——两条依赖正面相撞，实测炸在
`ImportError: cannot import name 'FromHarnessToBrainToolChooseOnceResp'
from partially initialized module`。

**为什么 `brain` 不直接用这一个类**：`brain` 自己不 import 它——它有自己
方言里的一份（`brain/interface/domain/model_call.py`），因为铁律 2 规定
`brain` 只依赖 `interfaces` + `schemas`，而"brain 的账"是 brain 交出来的
结果、不是跨层契约。`BrainTool` 在收账时把两份翻译一次（`_adopt()`）。

## 为什么大脑要把账"交出来"而不是自己记

**只有 Harness 写 trace。** 大脑是被调用方：它返回结果和账单，
由 Harness 翻译成事件。规则只有一句：**谁控制循环，谁记账。**
判定器碰不到自己的账是所有大脑调用的共同处境。

`payload` 直接就是 trace 里 `MODEL_CALL` 的内容。`error_kind` 非空时
Harness 会**另外补一条 `ERROR` 事件**——账单和失败模式是两件事：
前者回答"花了多少钱"，后者回答"为什么没拿到东西"，混在一条里两个都统计不出来。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelCall(BaseModel):
    """一次模型调用留下的账，外加它成没成。"""

    payload: dict[str, str | list[str]] = Field(
        default_factory=dict,
        description="token、延迟、原始输出（`raw`）、实际发给模型的文本输入"
        "（`prompt`，方便观测台/复盘直接看这次调用问了什么，不用去翻拼装代码）、"
        "实际发给模型的图（`images`，PNG data URI 列表）。"
        "**失败的调用也要有**——它同样烧了钱，而 `raw`/`prompt` 让你改进解析器之后能离线"
        "重算，不必再花 token 重跑",
    )
    error_kind: str = Field(
        default="",
        description="失败类型（ParseFailure / IllegalAction / OutputTruncated…）。"
        "空串表示这次成功了。**单独一列**：聚合失败模式时不必去解析 error 字符串",
    )
    error: str = Field(default="", description="失败详情，一句话")


ModelCallLog = list[ModelCall]
"""一次模型交互的全部尝试，按尝试先后排列：`list[ModelCall]`。

**失败的尝试也在里面**——它同样烧了 token，`error_kind` 会让渲染层为它补一条
`call_failed` 账。重试循环交回它就是完备的：宿主不需要知道"到底试了几次"。

**它住在这里而不是 trace 里**：`trace` 不认识 `ModelCall`（独立模块，只认
自己的词表与"不透明的 meta/content"），`harness` 又不该直接依赖 `providers`
拿它——所以家就在它的唯一读者旁边（带 `calls` 字段的信封、攒账的两个重试循环
的签名），再由 `schemas.harness` 的出口转交出去。批量记账信封
（`FromHarnessToTraceToolAppendModelCallsReq`）0916 删除之前它住在那个文件里。
"""


__all__ = ["ModelCall", "ModelCallLog"]
