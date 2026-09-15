"""`TraceToolPort` 的唯一实现：harness 和事件流之间那层"记账处理"。

持有 `TracePort`（事件流存储）。两个写方法分工一致——**调用方只组装信封，拆解规则
在本层**：

- `append()`：一笔账 → 按 `req.kind` 分派到 `render.py` 的渲染函数（正文格式、
  条件字段全在这层），一 req 可能渲成多条事件（账单 + 失败补 `call_failed`）；
- `append_model_calls()`：一次模型交互的 N 次尝试 → N 条调用账，拆解规则在
  `model_calls.py`。

**`meta` 由 harness 交齐、本层原样转发**（0914 跟进）：封套上的 `meta` 是一个
语义成分（harness 的签名信息），内容由调用方在 `req.meta` 里一次给全
（`source` / `episode_id` / `step`），`run_id` 由落盘那一层盖——本层不再替它拼。
拼完的 `meta` 与 `content` 都交给存储序列化成 JSON 字符串。

**读侧也在这层**：`read_events` 把"读磁盘账本"收进工具层，边界从此对称
——harness / api 一律不 import `pokemon_agent.trace`。

**本层是全项目唯一 import `pokemon_agent.trace` 的地方**（除 trace 自己）——
trace 是独立第三方模块，只有"桥"认识它。

**0913–0914 删掉的几件**：

- `project` 钩子（把 trace 的 `Event` 投成项目侧记录）——落盘形状现在就是 trace
  自己的六个字段；
- `event_sink` 双写（`RunDataCenter` 的内存事件镜像）——**磁盘账本是唯一真相**；
- `read_screenshot` / `read_event`（0914）：帧不再随事件落盘，画面真源搬到
  `memory/step_memory/*.json` 的 `before_frame`/`after_frame`。

**正文的字段格式是跨模块契约**：观测台前端按字段名渲染，格式变更权在本层
（见 `render.py` 模块 docstring）。链路名也在其中——错误账的 `content.link`。

**本包收拢三个 trace 相关文件**：`__init__.py`（分派器 + 端口实现）、
`render.py`（每种账的正文，纯函数）、`model_calls.py`（批量账）。
"""

from __future__ import annotations

from collections.abc import Iterable

from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    TraceEvent,
    TraceKind,
)
from pokemon_agent.trace import Event, EventType, LocalTrace, TracePort

from . import model_calls, render

_RENDERERS = {
    TraceKind.RUN_START: render.run_start,
    TraceKind.RUN_END: render.run_end,
    TraceKind.RUN_ERROR: render.run_error,
    TraceKind.EPISODE_START: render.episode_start,
    TraceKind.EPISODE_END: render.episode_end,
    TraceKind.EPISODE_ERROR: render.episode_error,
    # 七条链路各一种调用账：判定 / 校验各自多带一两个字段，其余共用 `model_call`。
    TraceKind.PERCEPTION_CALL: render.model_call,
    TraceKind.DECIDE_CALL: render.model_call,
    TraceKind.PLAN_CALL: render.model_call,
    TraceKind.JUDGE_CALL: render.judge_call,
    TraceKind.VERIFY_CALL: render.verify_call,
    TraceKind.SUMMARIZE_CALL: render.model_call,
    TraceKind.EXTRACT_CALL: render.model_call,
    # 三条错误账：`call_failed` 一般由 `model_call` 连带产出，登记一个渲染器
    # 让表完整（也有调用方按老路直接发它）。
    TraceKind.CALL_FAILED: render.call_failed,
    # `call_exhausted` 由五个失败点共用——链路名由调用方在 `req.link` 里自报
    # （0914 之前是五个派发键 + 五个写死链路名的渲染函数）。
    TraceKind.CALL_EXHAUSTED: render.call_exhausted,
    TraceKind.SUMMARY_PARSE_ERROR: render.episode_summary_error,
    TraceKind.OBSERVE: render.observe,
    TraceKind.THINK: render.think,
    TraceKind.DO_ACTION: render.do_action,
    TraceKind.STALL_CHECK: render.stall_check,
    TraceKind.GET_ACTION_SPACE: render.action_space,
    TraceKind.JUDGE_VERDICT: render.judge_verdict,
    TraceKind.VERIFY_VERDICT: render.verify_verdict,
    # 六条读口共用 `retrieve_node` 一个渲染函数，账名由 `req.kind` 定。
    TraceKind.READ_STEP: render.retrieve_node,
    TraceKind.READ_GLOBAL: render.retrieve_node,
    TraceKind.READ_KNOWLEDGE: render.retrieve_node,
    TraceKind.READ_OBJECT: render.retrieve_node,
    TraceKind.READ_VERIFY_STEP: render.retrieve_node,
    TraceKind.READ_VERIFY_KNOWLEDGE: render.retrieve_node,
    TraceKind.WRITE_STEP: render.memory_write,
    TraceKind.WRITE_OBJECT: render.object_note,
    TraceKind.WRITE_EPISODE: render.episode_memory_write,
    TraceKind.STEP_ADVANCE: render.step_advance,
    TraceKind.AFTER_ACTION: render.after_action,
    TraceKind.PLAN_VERDICT: render.plan_verdict,
}
"""账名 → 渲染函数。**没有翻译表**（0914）：渲染函数不再给账换名字，
落盘的 `kind` 就是 `req.kind`。"""


def _to_trace_event(raw: Event) -> TraceEvent:
    """读回来的一条事件 → 项目认识的那个类。

    入参按 `Event` 协议标注（不是 `Any`）：本层只承诺"给我一条 trace 事件"，
    具体是哪份实现与本函数无关。字段一致，转一手是为了让读端拿到**声明过的类型**。
    """
    return TraceEvent.model_validate(raw.model_dump())


class TraceTool:
    """`TraceToolPort` 的唯一实现。持有事件流存储（或任何 `TracePort` 实现）。

    **本对象自身的状态只有构造期常量**：它不跨步骤攒东西（读侧要的 `run_id`
    由 `LocalTrace` 自己持有，这里不再需要一份）。
    """

    def __init__(self, trace: TracePort) -> None:
        """接好事件流存储。"""
        self._trace = trace

    @classmethod
    def build(cls, *, run_id: str = "local") -> TraceTool:
        """接线工厂：造 `LocalTrace` 并包成 `TraceTool`。

        **全项目唯一 `new LocalTrace` 的地方**——装配点（`build.py`）只递裸字段，
        与 `BrainTool.build()` / `MemoryTool.build()` / `build_vision_provider()`
        同形（那三件是"选型知识收在 tool 层"的同一条定案）。
        """
        return cls(LocalTrace(run_id=run_id))

    def append(self, req: FromHarnessToTraceToolAppendReq) -> None:
        """记一笔账：按 `req.kind` 渲染正文，逐条落盘。

        `meta` **原样转发**（0914 跟进：它是封套的语义成分，内容由 harness 在
        `req.meta` 里一次交齐，本层只核"该有的在不在"，不再替它拼）。`run_id`
        由落盘那一层盖。

        前置条件：`req.meta` 带 `source`/`episode_id`/`step` 三件、不带 `run_id`；
        `req.kind` 对应的渲染函数所需字段非空（各渲染函数入口 assert 就地爆炸）。
        后置条件：所有渲染出的事件已落盘；每条的封套 `kind` **就是 `req.kind`**
        ——**例外是账单连带补出来的 `call_failed`**（那是另一本账，
        `type=error`），所以断言写成"要么是你点的那本账、要么是一条错误账"。
        """
        assert "run_id" not in req.meta, (
            f"{req.kind} 的 meta 带了 run_id——那个键归落盘这一层盖"
            "（`store._stamp_run_id`，调用方带了就是同一件事说两遍）"
        )
        missing = [key for key in ("source", "episode_id", "step") if key not in req.meta]
        assert not missing, (
            f"{req.kind} 的 meta 少了 {missing}——签名信息由 harness 在 `req.meta` 里一次交齐"
        )
        assert str(req.meta["source"]).strip(), (
            f"{req.kind} 的 meta.source 是空的——每笔账都要说清是哪个位置发的"
        )
        assert req.count is None, (
            f"{req.kind} 交了一份 count——那个槽 0914 跟进起已废："
            "六条读口的命中条数恒等于 `refs` 的长度，而 `refs` 已经是数组了"
        )
        renderer = _RENDERERS[req.kind]
        for rendered in _as_list(renderer(req)):
            assert rendered.kind == req.kind or rendered.type == EventType.ERROR, (
                f"{req.kind} 的渲染函数吐出了 {rendered.kind}——"
                "落盘的 kind 只许是请求的那本账，或一条连带产出的错误账"
            )
            self._trace.append(rendered.type, rendered.kind, dict(req.meta), rendered.content)

    def append_model_calls(self, req: FromHarnessToTraceToolAppendModelCallsReq) -> None:
        """记一次模型交互的**全部尝试**：一笔交互 → N 条调用账。

        与 `append` 同一分工——调用方只组装信封（签名信息 + `kind` 代表的链路 +
        原始尝试账），"怎么逐条摊开落账"是本层的事
        （`model_calls.append_model_calls`）。

        前置条件：`req.log` 按尝试顺序排列（重试循环保证）、`req.meta` 带齐
        三件签名（同 `append`）。
        后置条件：`req.log` 里每一条都已落盘；空 log 合法且不写任何事件。
        """
        model_calls.append_model_calls(self, req)

    # ---- 读：磁盘账本（唯一真相） ----

    def read_events(self, episode_id: str | None = None) -> list[TraceEvent]:
        """（契约见 `TraceToolPort.read_events`）读盘 + 还原成项目事件形状。"""
        return [_to_trace_event(e) for e in self._trace.read_events(episode_id)]


def _as_list(rendered: render.RenderedEvent) -> Iterable[render.Rendered]:
    """渲染函数的返回值归一：单条或一串，统一成可迭代。"""
    if isinstance(rendered, list):
        return rendered
    return [rendered]


__all__ = ["TraceTool"]
