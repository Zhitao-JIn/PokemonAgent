"""harness → `TraceTool` 的**批量记账**请求：一笔模型交互的全部尝试。

`FromHarnessToTraceToolAppendReq` 是"**一笔**账"，本信封是"**一次交互的 N 次尝试**"
——重试循环（决策 / 感知 / 规划三处）攒下来的原始材料一次交上来，由 tool 拆成 N 条
`MODEL_CALL`。这正是 `FromHarnessToTraceToolAppendReq` 那条 docstring 里写的
"必要时一拆多"：那个"多"在这里发生，所以拆的规则（`kind` = `MODEL_CALL`、每条带
自己的 `attempt`）住在 tool 层，不在 harness 里。

**为什么是信封、不是裸参数**：端口签名里出现的必须一律是 `schemas.harness` 的
信封——"harness 只认 schemas、不认任何模块的领域类型"这条边界靠它守住
（`tools/interface/ports.py` 的模块 docstring 立的就是这条）。

**`ModelCallLog` 为什么定义在本文件里**：它只服务于这一个信封（读者就两处——
本信封的 `log` 字段，和三个攒账的重试循环），所以它是**这个信封的内部件**：
不单独出一个文件、不进 `trace`、也不再有第二条 re-export 链。`trace` 被当作
**独立模块**对待——它只认自己的词表（`TraceKind`/`Source`/`EventType`）与
`payload: dict[str, str]` 裸字段，不认识 `ModelCall` 这类业务类型；"业务账 →
裸字段"的转换整个留给 tool 层（`tools/trace/render.py`）。这条边界就是
`pokemon_agent/trace/` 对 `pokemon_agent` 其余部分**零 import** 的由来。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.providers.interface import ModelCall
from pokemon_agent.trace import Source

ModelCallLog = list[tuple[int, ModelCall]]
"""一次模型交互的全部尝试，按 `attempt` 升序：`list[(attempt, ModelCall)]`。

**失败的尝试也在里面**——它同样烧了 token，`error_kind` 会让渲染层为它补一条
ERROR 事件。重试循环交回它就是完备的：宿主不需要知道"到底试了几次"。

它**住在这里而不是 trace 里**：`trace` 不认识 `ModelCall`（见模块 docstring），
`harness` 又不该直接依赖 `providers` 拿它——所以家就在它的唯一读者旁边，
再由 `schemas.harness` 的出口转交出去。
"""


class FromHarnessToTraceToolAppendModelCallsReq(BaseModel):
    """一次模型交互的尝试账：公共定位字段 + 这批账的出处。

    `source` 必填——`MODEL_CALL` 的渲染要用它标"这笔账属于哪一层"；
    `log` 可以为空——`ram_only=True` 的感知压根没调模型，那时什么都不写。
    `kind` 不在这里：本信封只有一种语义（`MODEL_CALL`），由 tool 自己声明。
    """

    episode_id: str
    step: int
    source: Source
    log: ModelCallLog
