"""`ModelCall`：一次模型调用留下的账，外加它成没成。

## 它为什么住在这里（曾经两度搬家）

| 时间 | 住址 | 理由 / 问题 |
|---|---|---|
| 最初 | `schemas/providers/domain/` | 当时 `providers` 还有自己的 schemas 子包 |
| 2026-09-12 | `providers/interface/domain/` | "它是 providers 的"——但**五个协议从不返回它** |
| 2026-09-13 | **这里** | `schemas/harness` 才是"harness 唯一认识的那一层" |

**为什么最终落在这里**——它跟 `ModelCallLog` 是同一个理由，见
`FromHarnessToTraceToolAppendModelCallsReq` 的模块 docstring：`harness` 侧
（`think_action`/`judge`/`verify_and_summarize`/`perceive_after_action`）
拿到账之后要**原样装进 `FromHarnessToTraceToolAppendReq.calls`** 交给 trace
渲染，而这个信封是 `schemas.harness` 的类型。**装得进去的前提是同一个类型**。

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
    """一次模型调用留下的账，外加它成没成。

    **不可变值语义**：`with_attempt()` 返回新对象（`model_copy`），不改自己
    ——重试循环里每一条账都要独立留档，共享可变状态会让"第几次尝试"互相覆盖。
    """

    payload: dict[str, str] = Field(
        default_factory=dict,
        description="token、延迟、第几次尝试、原始输出（`raw`）、实际发给模型的文本输入"
        "（`prompt`，方便观测台/复盘直接看这次调用问了什么，不用去翻拼装代码）。"
        "**失败的调用也要有**——它同样烧了钱，而 `raw`/`prompt` 让你改进解析器之后能离线"
        "重算，不必再花 token 重跑",
    )
    error_kind: str = Field(
        default="",
        description="失败类型（ParseFailure / IllegalAction / OutputTruncated…）。"
        "空串表示这次成功了。**单独一列**：聚合失败模式时不必去解析 error 字符串",
    )
    error: str = Field(default="", description="失败详情，一句话")

    def with_attempt(self, attempt: str) -> ModelCall:
        """盖上一次尝试的序号，返回**新对象**（本类是不可变值语义，不改自己）。

        **为什么 attempt 由循环控制者盖**：只有它知道"这是第几次"。
        brain 不重试，所以它产出的账里没有这一项；`BrainTool` 收到账之后
        在收进重试账那一刻统一盖上——这样无论成功还是失败路径，
        账上的 attempt 都完整。
        """
        return self.model_copy(update={"payload": {**self.payload, "attempt": attempt}})


__all__ = ["ModelCall"]
