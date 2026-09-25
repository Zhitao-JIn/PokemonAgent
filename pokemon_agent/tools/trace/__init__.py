"""`TraceToolPort` 的唯一实现：harness 和事件流之间那层"记账处理"。

持有 `TracePort`（事件流存储）。写只有 `append()` 一个口——**调用方只组装信封，
拆解规则在本层**：一笔账 → 按 `req.kind` 分派到 `render.py` 的渲染函数
（正文格式、条件字段全在这层），一 req 可能渲成多条事件——调用账的
`calls` 交的是**整条重试链**，渲染时逐条落成 `*_call` 账、失败的尝试
各自再补一条 `call_failed`（0916 统一：批量口 `append_model_calls` 已删，
此前七处调用点里成功路径走 `append(calls=…)`、失败路径走批量口，两套形状
落盘效果相同，只留一套）。

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

**本包收拢两个 trace 相关文件**：`__init__.py`（分派器 + 端口实现）、
`render.py`（每种账的正文，纯函数）。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendReq,
    TraceEvent,
    TraceKind,
)
from pokemon_agent.trace import Event, EventType, LocalTrace, TracePort

from . import render

_RENDERERS = {
    TraceKind.RUN_START: render.run_start,
    TraceKind.RUN_END: render.run_end,
    TraceKind.RUN_ERROR: render.run_error,
    TraceKind.EPISODE_START: render.episode_start,
    TraceKind.EPISODE_END: render.episode_end,
    TraceKind.EPISODE_ERROR: render.episode_error,
    TraceKind.TASK_START: render.task_start,
    TraceKind.TASK_END: render.task_end,
    TraceKind.TASK_ERROR: render.task_error,
    # 九条链路各一种调用账：判定 / 校验各自多带一两个字段，其余共用 `model_call`。
    TraceKind.SENSE_CALL: render.model_call,
    TraceKind.CHOOSE_CALL: render.model_call,
    TraceKind.PLAN_CALL: render.model_call,
    TraceKind.DECOMPOSE_CALL: render.model_call,
    TraceKind.JUDGE_CALL: render.judge_call,
    TraceKind.VERIFY_CALL: render.verify_call,
    TraceKind.SUMMARIZE_EPISODE_CALL: render.model_call,
    TraceKind.SUMMARIZE_TASK_CALL: render.model_call,
    # 三条错误账：`call_failed` 一般由 `model_call` 连带产出，登记一个渲染器
    # 让表完整（也有调用方按老路直接发它）。
    TraceKind.CALL_FAILED: render.call_failed,
    # `call_exhausted` 由五个失败点共用——链路名由调用方在 `req.link` 里自报
    # （0914 之前是五个派发键 + 五个写死链路名的渲染函数）。
    TraceKind.CALL_EXHAUSTED: render.call_exhausted,
    TraceKind.SUMMARY_PARSE_ERROR: render.episode_summary_error,
    TraceKind.SENSE_FRAME: render.sense_frame,
    TraceKind.CHOOSE_VERDICT: render.choose_verdict,
    TraceKind.PRESS_KEY: render.press_key,
    TraceKind.CHECK_STALL: render.check_stall,
    TraceKind.GET_ACTION_SPACE: render.action_space,
    TraceKind.JUDGE_VERDICT: render.judge_verdict,
    TraceKind.VERIFY_VERDICT: render.verify_verdict,
    # 六条读口共用 `retrieve_node` 一个渲染函数，账名由 `req.kind` 定。
    TraceKind.READ_ACT_MEMORY: render.retrieve_node,
    TraceKind.READ_EPISODE_MEMORY: render.retrieve_node,
    TraceKind.READ_KNOWLEDGE: render.retrieve_node,
    TraceKind.READ_OBJECT_MEMORY: render.retrieve_node,
    TraceKind.READ_TASK_MEMORY: render.retrieve_node,
    TraceKind.WRITE_ACT_MEMORY: render.memory_write,
    TraceKind.WRITE_OBJECT_MEMORY: render.object_note,
    TraceKind.WRITE_EPISODE_MEMORY: render.episode_memory_write,
    TraceKind.WRITE_TASK_MEMORY: render.task_memory_write,
    TraceKind.ADVANCE_STEP: render.advance_step,
    TraceKind.PLAN_VERDICT: render.plan_verdict,
    TraceKind.DECOMPOSE_VERDICT: render.decompose_verdict,
    TraceKind.SETTLE_GOAL: render.settle_goal,
    TraceKind.SETTLE_TASK: render.settle_task,
    TraceKind.CHECKPOINT_SAVE: render.checkpoint_save,
    TraceKind.CHECKPOINT_RESTORE: render.checkpoint_restore,
    TraceKind.CHECKPOINT_ERROR: render.checkpoint_error,
    TraceKind.WORLD_SNAPSHOT: render.world_snapshot,
    TraceKind.TRACE_SEALED: render.trace_sealed,
    TraceKind.REVIEW_INJECT: render.review_inject,
    TraceKind.REVIEW_AUDIT: render.review_audit,
}
"""账名 → 渲染函数。**没有翻译表**（0914）：渲染函数不再给账换名字，
落盘的 `kind` 就是 `req.kind`。"""


_LEGACY_KIND_ALIASES: dict[str, str] = {
    "read_step": "read_act_memory",
    "write_step": "write_act_memory",
    "read_verify_step": "read_task_memory",
    "read_verify_knowledge": "read_knowledge",
}
"""历史 trace 的旧 kind 值 → 新值（0923 断代表）。只在渲染读侧兜底。"""


def _to_trace_event(raw: Event) -> TraceEvent:
    """读回来的一条事件 → 项目认识的那个类。

    入参按 `Event` 协议标注（不是 `Any`）：本层只承诺"给我一条 trace 事件"，
    具体是哪份实现与本函数无关。字段一致，转一手是为了让读端拿到**声明过的类型**。
    """
    return TraceEvent.model_validate(raw.model_dump())


def render_request(req: FromHarnessToTraceToolAppendReq) -> list[render.Rendered]:
    """一笔账 → 要落盘的那几条（`type`、`kind`、正文对象）。`TraceTool.append` 与回放比对共用。

    后置条件：每条的 `kind` 就是 `req.kind`，**例外是账单连带补出来的错误账**（`type=error`）。
    失败：`req.kind` 没有渲染函数 → `KeyError`。
    """
    renderer = _RENDERERS.get(req.kind)
    if renderer is None and getattr(req.kind, "value", None) in _LEGACY_KIND_ALIASES:
        # **断代兼容**（0923 189/190）：187–190 压格与记忆阶梯把一批 `kind`
        # 改了名（read_step→read_act_memory、write_step→write_act_memory、read_verify_step→
        # read_task_memory…）。新账一律用新名；读到**历史 trace** 的旧名时
        # 按同族渲染函数兜住——只保证"能渲"，不保证逐字段语义仍在。
        renderer = _RENDERERS[TraceKind(_LEGACY_KIND_ALIASES[req.kind.value])]
    if renderer is None:
        raise KeyError(req.kind)
    out = _as_list(renderer(req))
    for rendered in out:
        assert rendered.kind == req.kind or rendered.type == EventType.ERROR, (
            f"{req.kind} 的渲染函数吐出了 {rendered.kind}——"
            "落盘的 kind 只许是请求的那本账，或一条连带产出的错误账"
        )
    return out


class TraceTool:
    """`TraceToolPort` 的唯一实现。持有事件流存储（或任何 `TracePort` 实现）。

    **本对象自身的状态只有构造期常量**：它不跨步骤攒东西（读侧要的 `run_id`
    由 `LocalTrace` 自己持有，这里不再需要一份）。构造期常量里有本执行线的分支血缘
    （`branch` 与 `lineage`），读侧按它拼出"这条执行线看得见的全部账"。
    """

    def __init__(
        self,
        trace: TracePort,
        *,
        branch: str = "main",
        lineage: Sequence[tuple[str, str, float]] = (),
    ) -> None:
        """接好事件流存储与本执行线的血缘。

        branch：本执行线的分支名（与存储盖进 `meta` 的那个同值）。
        lineage：祖先执行线，由根到父，每条 `(分支名, 分叉点事件 uuid, 分叉点事件 ts)`；
            未经恢复的执行线为空。读侧对每个祖先只取分叉点及之前的事件。
        """
        assert branch, "TraceTool needs a non-empty branch"
        assert branch not in {b for b, _u, _t in lineage}, "branch 不能出现在自己的血缘里"
        self._trace = trace
        self._branch = branch
        self._lineage = tuple(lineage)

    @classmethod
    def build(
        cls,
        *,
        run_id: str = "local",
        trace_root: str | Path | None = None,
        branch: str = "main",
        lineage: Sequence[tuple[str, str, float]] = (),
    ) -> TraceTool:
        """接线工厂：造 `LocalTrace` 并包成 `TraceTool`。

        **全项目唯一 `new LocalTrace` 的地方**——装配点（`build.py`）只递裸字段，
        与 `BrainTool.build()` / `MemoryTool.build()` / `build_vision_provider()`
        同形（那三件是"选型知识收在 tool 层"的同一条定案）。

        `trace_root`：落盘根（一条事件一个文件那个目录），缺省为**进程启动目录**
        下的 `tracelog/`（0916 起）。启动参数 `--trace-root` →
        `build_real(trace_root=…)` → 这里 → `LocalTrace(root=…)`。

        `branch` / `lineage`：本执行线的分支名与祖先血缘（见 `__init__`）；未经恢复时用缺省。
        """
        return cls(
            LocalTrace(run_id=run_id, root=trace_root, branch=branch),
            branch=branch,
            lineage=lineage,
        )

    def append(self, req: FromHarnessToTraceToolAppendReq) -> None:
        """记一笔账：按 `req.kind` 渲染正文，逐条落盘。

        `meta` **原样转发**（0914 跟进：它是封套的语义成分，内容由 harness 在
        `req.meta` 里一次交齐，本层只核"该有的在不在"，不再替它拼）。`run_id`
        由落盘那一层盖。

        前置条件：`req.meta` 带 `source`/`episode_id`/`task_id`/`step` 四件、
        不带 `run_id` / `branch`；
        `req.kind` 对应的渲染函数所需字段非空（各渲染函数入口 assert 就地爆炸）。
        后置条件：所有渲染出的事件已落盘；每条的封套 `kind` **就是 `req.kind`**
        ——**例外是账单连带补出来的 `call_failed`**（那是另一本账，
        `type=error`），所以断言写成"要么是你点的那本账、要么是一条错误账"。
        """
        assert "branch" not in req.meta, f"{req.kind} 的 meta 带了 branch——那个键归落盘这一层盖"
        assert "run_id" not in req.meta, (
            f"{req.kind} 的 meta 带了 run_id——那个键归落盘这一层盖"
            "（`store._stamp_run_id`，调用方带了就是同一件事说两遍）"
        )
        missing = [
            key for key in ("source", "episode_id", "task_id", "step") if key not in req.meta
        ]
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
        for rendered in render_request(req):
            self._trace.append(rendered.type, rendered.kind, dict(req.meta), rendered.content)

    # ---- 读：磁盘账本（唯一真相） ----

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        """（契约见 `TraceToolPort.read_events`）读盘 + 还原成项目事件形状。

        `meta` 原样转给 `TracePort.read_events`——交集匹配怎么做是存储层的事，
        本层只做形状还原（`Event` 协议 → `TraceEvent`）与**按血缘拼接**：

        - `meta` 为空：不过滤，整个落盘根原样返回（与血缘无关）；
        - `meta` 自带 `branch` 键：按调用方给的分支读，不拼血缘；
        - 其余：对血缘里每个祖先分支取"分叉点及之前"的匹配事件，再加上本分支的全部
          匹配事件——即这条执行线看得见的全部账（`docs/spec/checkpoint/SPEC.md` §三）。

        后置条件：按 `(ts, uuid)` 升序。
        """
        if not meta or "branch" in meta:
            return [_to_trace_event(e) for e in self._trace.read_events(meta)]
        # 步骤 1：祖先各取分叉点及之前，本分支全取。
        picked: list[Event] = []
        for branch, fork_uuid, fork_ts in self._lineage:
            picked.extend(
                e
                for e in self._trace.read_events({**meta, "branch": branch})
                if (e.ts, e.uuid) <= (fork_ts, fork_uuid)
            )
        picked.extend(self._trace.read_events({**meta, "branch": self._branch}))
        # 步骤 2：合并后按落盘序排好。
        picked.sort(key=lambda e: (e.ts, e.uuid))
        return [_to_trace_event(e) for e in picked]


def _as_list(rendered: render.RenderedEvent) -> Iterable[render.Rendered]:
    """渲染函数的返回值归一：单条或一串，统一成可迭代。"""
    if isinstance(rendered, list):
        return rendered
    return [rendered]


__all__ = ["TraceTool", "render_request"]
