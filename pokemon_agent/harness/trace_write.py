"""harness 侧写 trace 的共用件：把 util 交回的**尝试账**落成事件。

**为什么需要它**：三个 util（`brain_utils`/`game_utils`/`run_plan_utils`）的重试循环不长在
节点里，但账要写在节点里——util 只交回 `ModelCallLog`（每一次尝试的原始材料），由宿主
（节点 / 图外的局方法）落到 trace 上。规则是"**账写在它的宿主里**"：宿主是节点就写节点，
是图外的局/run 方法就写那个方法。

改之前是"**谁的循环谁记账**"——util 边重试边写。换掉它的理由与代价（崩溃窗口）见
`docs/spec/harness/PLAN_graph_readability.md` §3.7.4。

这段 `AppendReq` 样板有 5 个写点（`think_action` / `perceive_after_action` /
`EpisodeHarness._perceive` / `RunHarness.plan`），所以抽成一个纯函数——**它只做拼装，
不判断该不该写**，那个判断永远在宿主手里。
"""

from __future__ import annotations

from pokemon_agent.providers import ModelCall
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq
from pokemon_agent.tools.interface import TraceToolPort
from pokemon_agent.trace import Source, TraceKind

ModelCallLog = list[tuple[int, ModelCall]]
"""一次模型交互的**全部尝试**：`(第几次尝试, 那一次的账)`，按 `attempt` 升序。

**失败的尝试也在里面**——它同样烧了 token，`error_kind` 会让渲染层为它补一条 ERROR
事件。util 交回它就是完备的：宿主不需要知道"到底试了几次"。
"""


def append_model_calls(
    trace: TraceToolPort,
    *,
    episode_id: str,
    step: int,
    source: Source,
    log: ModelCallLog,
) -> None:
    """把一次模型交互的尝试账逐条写进 trace。

    **顺序即尝试顺序**：同一次尝试可能吐多条事件（`model_call` 渲染层会为带
    `error_kind` 的账补一条 ERROR），但事件流里的相对次序与"边重试边写"完全一致
    ——重试循环期间没有别的写账点，`event_id` 的相对次序不变。

    前置条件：`log` 的 `attempt` 升序（util 保证）；空 log 是合法的（`ram_only=True`
    的感知压根没调模型），那时什么也不写。
    """
    for attempt, call in log:
        trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.MODEL_CALL,
                episode_id=episode_id,
                step=step,
                source=source,
                call=call,
                attempt=attempt,
            )
        )
