"""`LangfuseTrace`：用本机 Langfuse v4 实现事件流 `TracePort`。

树形约定（0927 定稿，与 `langfuse-spec.md` §六同步）：

- **meta 的执行线标识归调用方盖**（0927 定案）：`run_id` / `branch` 由 tool 层
  （`TraceTool.append`）在调用时盖进 `meta`，本模块对它们**零持有**——只在路由时读
  `meta` 里的值（位约定判据、scope 命名）。构造期唯一需要的是 `trace_id`
  （调用方用 `client.create_trace_id(seed=run_id)` 造好递进来）。
- **branch scope 是顶层锚**：首笔 append 时建一个 `branch:<branch>` scope
  （无父，metadata 带 `scope_kind="branch"`；名字取自 meta 的 `branch`）。
  恢复线因此不再有"构造即建"的第二个 run root 空壳。
- **`run_start` 是 run 层锚**：真账挂 branch scope 下，并注册 `("run",)` 锚——
  run 层其余账（run 的 perceive/plan、`settle_goal`、`run_end`/`run_error`）都挂它下面。
  harness 的 meta 位约定（`run/begin` 注释，0928 定稿）：run 级账的 `episode_id`/`task_id`
  位放 `run_id`、**episode 级账的 `task_id` 位清空**（episode 账不需要 task 坐标）、
  task 级账的 `task_id` 位放真 task 号——路由判据据此把它们各归各层。
- **`episode_start` / `task_start` 各自是 episode / task 层锚**：分别挂上一层锚下，
  并注册 `("episode", branch, episode_id)` / `("task", …)` 锚。**step 不建 scope**
  （0928 定稿：Dashboard 三层 step 平铺观感乱）——真 task 层账直接挂 task 锚下，
  step 号标注进账名（`kind (step:N)`），`task_start` 是最小的分组锚。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .interface.event import Event
from .langfuse_support import (
    LANGFUSE_ADAPTER_VERSION,
    RETRIEVE_KINDS,
    LangfuseClientPort,
    build_client_from_environment,
    create_error_event,
    create_scope_observation,
    decode_observation_event,
    generation_input_fields,
    json_decode_meta,
    matches_meta,
    new_event_envelope,
    read_observations,
    retrieve_input_fields,
    stamp_generation_fields,
)
from .seq import next_seq
from .store import new_event_uuid

logger = logging.getLogger(__name__)

_MIN_SPAN_SECONDS = 0.003
"""每个 observation 落库时垫的最小时长（2026-09-27）。

"创建即结束"的 span 在 OTEL 毫秒精度下 start==end，Dashboard 把 duration=0 的行
**整行折叠时间段**。垫 3ms 让每行都有非零时长可显示——scope 锚与事件账统一。
真实操作时长在封套 `started_at`/`ended_at`（操作发生在落账之前，span 窗口只是
记账瞬间），这里的数字不是计时、只求可见。
"""


_ANCHOR_KINDS = frozenset(
    {
        "task_start",
        "task_end",
        "task_error",
    }
)
"""生命周期锚账的 kind——这些账即便 meta 带真 task 号也不标 `step:N`：
名字是树形结构与恢复伪造的匹配键（`_remember_scope` / smoke / 测试按名核对），
必须稳定。run/episode 层生命周期账的 task 位是占位（run_id / 空，0928 定稿），
天然不进 `_is_task_step_account` 分支，无需列入。"""


class LangfuseTrace:
    """`TracePort` 实现：事件只写入 Langfuse，不创建 LocalTrace 副本。"""

    def __init__(
        self,
        *,
        trace_id: str,
        client: LangfuseClientPort | None = None,
    ) -> None:
        """绑定一条已定好的 Langfuse trace 并创建（或注入）SDK 客户端。

        `trace_id` 由调用方（tool 层）用 `client.create_trace_id(seed=run_id)` 造好
        递进来——同一 run 与 branch 定址得到同一条 trace，靠的正是
        "同 seed 同 trace_id"。本模块对 run_id / branch **零持有**：两者只作为
        `meta` 的键随每笔账进来（tool 层盖章），路由与 scope 命名读 meta。
        """
        if not trace_id:
            raise ValueError("LangfuseTrace needs a non-empty trace_id")
        self._trace_id = trace_id
        self._client = client if client is not None else build_client_from_environment()
        self._scopes: dict[tuple[str, ...], str] = {}
        self._branch_scope_id: str | None = None

    def append(
        self,
        type: str,
        kind: str,
        meta: dict[str, Any] | None = None,
        content: Any = None,  # noqa: ANN401
        *,
        started_at: float | None = None,
        ended_at: float | None = None,
    ) -> str:
        """Append a losslessly encoded observation and return its local event UUID.

        前置条件：`meta` 已由 tool 层盖好 `run_id` / `branch`（本模块零持有，
        缺了当场拒绝）；`branch` 参与路由与 scope 命名。
        本类取双后端共享的进程内全局递增 `seq`（重启置零）——进封套与
        observation metadata，观测侧对账用；不参与 Langfuse 的 OTEL 排序
        （span 时间轴由 3ms 垫错开，那是另一回事）。
        `started_at` / `ended_at`：操作真实起止（None 补记账时刻）——双时刻
        只进封套；Langfuse 侧 span 的 OTEL 时间轴是另一回事（档二前不回拨）。
        """
        stamped_meta = dict(meta or {})
        assert "run_id" in stamped_meta and "branch" in stamped_meta, (
            "meta 必须已盖 run_id / branch——盖章在 tool 层（TraceTool.append），本模块只透传"
        )
        seq = next_seq()
        event_uuid = new_event_uuid()
        now = time.time()
        envelope = new_event_envelope(
            event_uuid,
            seq,
            kind,
            type,
            float(started_at) if started_at is not None else now,
            float(ended_at) if ended_at is not None else now,
            stamped_meta,
            content,
        )
        parent_id = self._parent_for(kind, stamped_meta)
        metadata = self._observation_metadata(event_uuid, kind, type, stamped_meta)
        metadata["seq"] = seq
        context = {"trace_id": self._trace_id}
        if parent_id:
            context["parent_span_id"] = parent_id
        # Langfuse 观测类型与 input 三分（2026-09-27 字段适配定案）：input=请求面
        # ——generation 投 prompt/images（模型调用的请求）、retriever 投 query（检索
        # 的请求）；其余账的"输入"没有独立语义，input 置 None（封套在 output 是
        # 唯一真源，local_event_uuid 已在 metadata，不重复占位）。
        if type == "model_call":
            observation_type = "generation"
        elif kind in RETRIEVE_KINDS:
            observation_type = "retriever"
        else:
            observation_type = "span"
        kwargs: dict[str, Any] = {
            "trace_context": context,
            "name": self._display_name(kind, stamped_meta),
            "as_type": observation_type,
            "version": LANGFUSE_ADAPTER_VERSION,
            "input": None,
            "output": {"pokemon_trace": envelope},
            "metadata": metadata,
        }
        if observation_type == "generation":
            kwargs.update(stamp_generation_fields(content))
            kwargs["input"] = generation_input_fields(content) or kwargs["input"]
        elif observation_type == "retriever":
            kwargs["input"] = retrieve_input_fields(content) or kwargs["input"]
        if type == "error":
            observation_id = create_error_event(
                self._client,
                context,
                kind,
                kwargs["input"],
                kwargs["output"],
                metadata,
            )
        else:
            with self._client.start_as_current_observation(**kwargs) as observation:
                # OTEL span 毫秒精度下，"创建即结束"的账 start==end（duration=0），
                # Dashboard 会把时间段整行折叠（2026-09-27 实测）。垫一拍让每行
                # 都有非零时长可显示；**真实操作时长在封套 started_at/ended_at**
                # （操作发生在落账之前，span 窗口只是记账瞬间），这里不是计时。
                time.sleep(_MIN_SPAN_SECONDS)
                observation_id = observation.id
        self._remember_scope(kind, stamped_meta, observation_id)
        if kind in {"run_end", "run_error"}:
            self.flush()
        return event_uuid

    def read_events(self, meta: dict[str, Any] | None = None) -> list[Event]:
        """Read currently visible observations, filter by metadata and sort by local time."""
        wanted = dict(meta or {})
        events: list[Event] = []
        for observation in read_observations(self._client, self._trace_id):
            event = decode_observation_event(observation)
            if event is None:
                continue
            decoded_meta = json_decode_meta(event.meta)
            if decoded_meta is not None and matches_meta(decoded_meta, wanted):
                events.append(event)
        return sorted(events, key=lambda event: (event.ended_at, event.seq))

    def flush(self) -> None:
        """Flush the SDK queue; query visibility can still be delayed."""
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning("Langfuse flush failed: %s", exc)

    def shutdown(self) -> None:
        """Shut down the SDK background worker."""
        try:
            self._client.shutdown()
        except Exception as exc:
            logger.warning("Langfuse shutdown failed: %s", exc)

    # ---- 父解析与 scope 注册表 ----

    def _parent_for(self, kind: str, meta: dict[str, Any]) -> str:
        run_id = str(meta.get("run_id", ""))
        branch = str(meta["branch"])
        branch_scope = self._ensure_branch_scope(meta)
        if kind == "run_start":
            return branch_scope
        if kind in {"episode_start", "episode_end", "episode_error"}:
            if kind == "episode_start":
                return self._scopes.get(("run",), branch_scope)
            return self._episode_scope(meta, branch_scope)
        episode = str(meta.get("episode_id", ""))
        if kind in {"task_start", "task_end", "task_error"}:
            episode_scope = self._episode_scope(meta, branch_scope)
            if kind == "task_start":
                return episode_scope
            task_scope = self._scopes.get(("task", branch, episode, str(meta.get("task_id", ""))))
            return task_scope or episode_scope
        task = str(meta.get("task_id", ""))
        # harness 的位约定（run/begin 注释，0928 定稿）：run 级账的 episode/task 位放
        # run_id、episode 级账的 task 位清空——task 位非空且 != run_id 的只有 task 层账。
        if episode and task and task != run_id:
            # step 不建 scope（0928 定稿）：操作账直接挂 task 锚（开局 save 等
            # 先于 task_start 落账的，退 episode 锚，不再抢建 scope）。
            task_scope = self._scopes.get(("task", branch, episode, task))
            if task_scope:
                return task_scope
        if episode and episode != run_id:
            episode_scope = self._episode_scope(meta, branch_scope)
            if episode_scope:
                return episode_scope
        # run 层账（episode_id 缺省或等于 run_id）：挂 run_start 锚，没有则 branch scope。
        return self._scopes.get(("run",), branch_scope)

    def _observation_metadata(
        self, event_uuid: str, kind: str, event_type: str, meta: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "local_event_uuid": event_uuid,
            "event_kind": kind,
            "event_type": event_type,
            "event_meta": meta,
        }

    def _remember_scope(self, kind: str, meta: dict[str, Any], observation_id: str) -> None:
        branch = str(meta["branch"])
        episode = str(meta.get("episode_id", ""))
        task = str(meta.get("task_id", ""))
        if kind == "run_start":
            self._scopes[("run",)] = observation_id
        elif kind == "episode_start":
            self._scopes[("episode", branch, episode)] = observation_id
        elif kind == "task_start":
            self._scopes[("task", branch, episode, task)] = observation_id

    def _ensure_branch_scope(self, meta: dict[str, Any]) -> str:
        """首笔账时建本执行线的 branch scope（顶层锚）；此后复用。名字取 meta 的 branch。"""
        branch = str(meta["branch"])
        if self._branch_scope_id is None:
            metadata: dict[str, Any] = {
                "scope_kind": "branch",
                "run_id": str(meta.get("run_id", "")),
                "branch": branch,
            }
            self._branch_scope_id = create_scope_observation(
                self._client, self._trace_id, f"branch:{branch}", metadata, None
            )
            self._scopes[("branch", branch)] = self._branch_scope_id
        return self._branch_scope_id

    def _episode_scope(self, meta: dict[str, Any], branch_scope: str) -> str:
        """episode 锚：有真 scope 用真 scope；尚未开始时回退到 branch scope。"""
        branch = str(meta["branch"])
        episode = str(meta.get("episode_id", ""))
        key = ("episode", branch, episode)
        if key in self._scopes:
            return self._scopes[key]
        return branch_scope

    @staticmethod
    def _is_task_step_account(meta: dict[str, Any]) -> bool:
        """真 task 层的操作账（0928 定稿位约定：task 位非空且 != run_id 的只有 task 层账——
        run 层账的 task 位放 run_id，episode 层账的 task 位清空）。"""
        run_id = str(meta.get("run_id", ""))
        episode = str(meta.get("episode_id", ""))
        task = str(meta.get("task_id", ""))
        return bool(episode and task and task != run_id)

    @staticmethod
    def _display_name(kind: str, meta: dict[str, Any]) -> str:
        """UI 账名：task 层操作账把 step 号放**前缀**（`step:N {kind}`，0928 定稿）。

        为什么是前缀：Dashboard 树形视图同级按 startTime 排（时间序天然就是产生序），
        账名不参与排序——前缀的价值在**行首扫读**：step 边界在名字开头一眼可见，
        不同 step 的账平铺在同一个 task 锚下时不至于混作一团。
        task 层 `*_start/*_end/*_error` 生命周期锚账不标，它们的名字是树形结构匹配键。
        """
        if kind in _ANCHOR_KINDS or not LangfuseTrace._is_task_step_account(meta):
            return kind
        return f"step:{meta.get('step', 0)} {kind}"


__all__ = ["LangfuseTrace"]
