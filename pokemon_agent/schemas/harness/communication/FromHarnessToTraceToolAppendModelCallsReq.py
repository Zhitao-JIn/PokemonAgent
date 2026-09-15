"""harness → `TraceTool` 的**批量记账**请求：一笔模型交互的全部尝试。

`FromHarnessToTraceToolAppendReq` 是"**一笔**账"，本信封是"**一次交互的 N 次尝试**"
——重试循环（决策 / 感知 / 规划三处）攒下来的原始材料一次交上来，由 tool 拆成 N 条
`*_call` 账。这正是 `FromHarnessToTraceToolAppendReq` 那条 docstring 里写的
"必要时一拆多"：那个"多"在这里发生，所以拆的规则（每条带自己的 `attempt`）住在
tool 层，不在 harness 里。

**`kind` 就是账名**（0914 去翻译表）：取七个 `*_CALL` 之一，落盘封套上的 `kind`
与它逐字同值；**链路名（`decide`…）是另一维**，由 `render._CALL_LINK` 给，
落进错误账的 `content.link`。

**为什么是信封、不是裸参数**：端口签名里出现的必须一律是 `schemas.harness` 的
信封——"harness 只认 schemas、不认任何模块的领域类型"这条边界靠它守住
（`tools/interface/ports.py` 的模块 docstring 立的就是这条）。

**`ModelCallLog` 为什么定义在本文件里**：它只服务于这一个信封（读者就两处——
本信封的 `log` 字段，和三个攒账的重试循环），所以它是**这个信封的内部件**：
不单独出一个文件、不进 `trace`、也不再有第二条 re-export 链。`trace` 被当作
**独立模块**对待——它只认自己的词表（`EventType`）与"不透明的 meta/content"，
不认识 `ModelCall` 这类业务类型；"业务账 → 正文"的转换整个留给 tool 层
（`tools/trace/render.py`）。这条边界就是 `pokemon_agent/trace/` 对
`pokemon_agent` 其余部分**零 import** 的由来。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from pokemon_agent.schemas.harness.domain import TraceKind

from .ModelCall import ModelCall

ModelCallLog = list[ModelCall]
"""一次模型交互的全部尝试，按 `attempt` 升序：`list[(attempt, ModelCall)]`。

**失败的尝试也在里面**——它同样烧了 token，`error_kind` 会让渲染层为它补一条
`call_failed` 账。重试循环交回它就是完备的：宿主不需要知道"到底试了几次"。

它**住在这里而不是 trace 里**：`trace` 不认识 `ModelCall`（见模块 docstring），
`harness` 又不该直接依赖 `providers` 拿它——所以家就在它的唯一读者旁边，
再由 `schemas.harness` 的出口转交出去。
"""


class FromHarnessToTraceToolAppendModelCallsReq(BaseModel):
    """一次模型交互的尝试账：签名信息（`meta`）+ 这批账属于哪条链。

    `kind` 取 `TraceKind` 的七个调用类之一（`PERCEPTION_CALL` / `DECIDE_CALL` /
    `PLAN_CALL` / `JUDGE_CALL` / `VERIFY_CALL` / `SUMMARIZE_CALL` / `EXTRACT_CALL`）
    ——它**既落封套的 `kind`，也是"这次调用属于哪条链"的唯一声明**（渲染层按
    `render._CALL_LINK` 取链路名，落进错误账的 `content.link`）。
    `log` 可以为空——`ram_only=True` 的感知压根没调模型，那时什么都不写。

    `meta`：与 `FromHarnessToTraceToolAppendReq.meta` 同一个槽、同一个契约——
    `*_CALL` 账由拿 resp 的那一格自报。
    """

    kind: TraceKind
    meta: dict[str, Any]
    log: ModelCallLog
