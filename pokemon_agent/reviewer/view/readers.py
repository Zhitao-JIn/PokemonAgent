"""Reviewer 查询门面：只调用窄读端口，取帧与文本展示分开。"""

import json

from pokemon_agent.schemas.harness import FromHarnessToMemoryToolRecallReq, TraceEvent
from pokemon_agent.schemas.reviewer import FrameQuery, RecallQuery, TraceQuery, ViewAnswer

from .ports import MemoryReader, TraceReader
from .render import event_line, image_uri, text_without_frames


class ViewReaders:
    """查询不会写 trace 或记忆正文；recall 的派生缓存刷新沿用服务端行为。"""

    def __init__(
        self, trace: TraceReader | None, memory: MemoryReader | None, *, trace_delayed: bool = False
    ) -> None:
        self._trace = trace
        self._memory = memory
        self._trace_delayed = trace_delayed

    def read_trace(self, q: TraceQuery, *, default_run_id: str) -> ViewAnswer:
        """等值筛选后按当前事件契约排序，从尾部翻页；读取失败返回可展示的失败结果。"""
        if self._trace is None:
            return ViewAnswer(ok=False, text="读端口未接入")
        meta = {"run_id": q.run_id or default_run_id}
        meta.update(
            {
                key: getattr(q, key)
                for key in ("episode_id", "task_id", "source")
                if getattr(q, key) is not None
            }
        )
        try:
            events = self._events(meta)
        except (OSError, RuntimeError, ValueError) as exc:
            return _failure(exc)
        if q.kind is not None:
            events = [event for event in events if event.kind == q.kind]
        end = max(0, len(events) - q.offset)
        page = events[max(0, end - q.last_n) : end]
        header = (
            f"trace run_id={meta['run_id']}：共 {len(events)} 条，"
            f"返回 {len(page)} 条，offset={q.offset}"
        )
        if self._trace_delayed:
            header += "（可能不含最近几秒）"
        lines = [header, *(event_line(event, q.content_limit) for event in page), "--- 结束 ---"]
        return ViewAnswer(ok=True, text="\n".join(text_without_frames(line) for line in lines))

    def recall(self, q: RecallQuery) -> ViewAnswer:
        """原样传 query/hint/limit，不强加 run_id；正文及 payload 的画面全部省略。"""
        if self._memory is None:
            return ViewAnswer(ok=False, text="读端口未接入")
        req = FromHarnessToMemoryToolRecallReq(
            query=q.query, conditions=dict(q.conditions), limit=q.limit
        )
        try:
            response = self._memory.recall(req)
        except (OSError, RuntimeError, ValueError) as exc:
            return _failure(exc)
        items = response.items[: q.limit]
        lines = [f"recall query={q.query!r} conditions={q.conditions}：返回 {len(items)} 条"]
        for item in items:
            lines.append(f"{item.kind} · {item.uuid} · score={item.score}")
            lines.append(text_without_frames(item.content))
            lines.append(text_without_frames(item.payload))
        lines.append("--- 结束 ---")
        return ViewAnswer(ok=True, text="\n".join(text_without_frames(line) for line in lines))

    def read_frame(self, q: FrameQuery, *, default_run_id: str) -> ViewAnswer:
        """latest 读 sense_frame，其余从不限量的本局 act 结果按 step 精确取一帧。"""
        try:
            if q.which == "latest":
                return self._latest_frame(default_run_id)
            return self._act_frame(q)
        except (OSError, RuntimeError, ValueError) as exc:
            return _failure(exc)

    def _events(self, meta: dict[str, str]) -> list[TraceEvent]:
        """不修改端口返回的列表，统一按当前 ended_at / seq 排序。"""
        assert self._trace is not None
        return sorted(self._trace.read_events(meta), key=lambda event: (event.ended_at, event.seq))

    def _latest_frame(self, run_id: str) -> ViewAnswer:
        """只认最新 sense_frame；最新账缺帧时不冒充返回更老的画面。"""
        if self._trace is None:
            return ViewAnswer(ok=False, text="读端口未接入")
        events = [
            event for event in self._events({"run_id": run_id}) if event.kind == "sense_frame"
        ]
        if not events:
            return ViewAnswer(ok=False, text="没有 sense_frame 画面")
        content = json.loads(events[-1].content)
        uri = image_uri(content.get("frame")) if isinstance(content, dict) else None
        label = f"run_id={run_id} latest · {events[-1].uuid}"
        if self._trace_delayed:
            label += "（可能不含最近几秒）"
        return _frame_answer(uri, label)

    def _act_frame(self, q: FrameQuery) -> ViewAnswer:
        """limit=None 避免超过默认八条后静默丢掉目标步。"""
        assert q.episode_id is not None and q.step is not None
        if self._memory is None:
            return ViewAnswer(ok=False, text="读端口未接入")
        response = self._memory.recall(
            FromHarnessToMemoryToolRecallReq(conditions={"episode_id": q.episode_id}, limit=None)
        )
        for item in response.items:
            payload = item.payload
            if (
                item.kind == "act"
                and payload.get("episode_id") == q.episode_id
                and payload.get("step") == q.step
            ):
                uri = image_uri(payload.get(f"{q.which}_frame"))
                return _frame_answer(uri, f"{q.episode_id} step={q.step} {q.which}")
        return ViewAnswer(ok=False, text="未找到该步 act 记忆")


def _frame_answer(uri: str | None, label: str) -> ViewAnswer:
    """图片仅经 images 返回；文字只展示来源。"""
    if uri is None:
        return ViewAnswer(ok=False, text="该条目没有有效画面")
    return ViewAnswer(ok=True, text=text_without_frames(label), images=[uri])


def _failure(exc: OSError | RuntimeError | ValueError) -> ViewAnswer:
    """正常读取失败可展示；异常消息也不能泄露内嵌图片。"""
    return ViewAnswer(ok=False, text=text_without_frames(f"查询失败：{exc}"))
