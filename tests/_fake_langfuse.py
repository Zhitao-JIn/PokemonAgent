"""Langfuse SDK 的离线假件：一个可注入 `LangfuseTrace` 的 fake client。

**为什么值得一个文件**：`LangfuseTrace`（`trace/langfuse_trace.py`）的全部 SDK 接触面
收敛在 `langfuse_support.LangfuseClientPort` 这一小块——`create_trace_id` /
`start_observation` / `start_as_current_observation` / `create_event` / `flush` /
`shutdown`，外加 `client.api.observations.get_many(...)` 一个读口。这个假件按同一形状
实现，把每次调用**原样记录**下来，测试据此断言"trace 交给了 SDK 什么"。

**不连网、不装真 SDK 也能跑**（但仓库环境已装 `langfuse` 4.15.6，签名逐一对过）：
分页由假 API 自己的 `page_size` 控制（真实现传的 `limit` 恒为 1000，测试里用小页
逼出多页路径）；查询失败与卡死游标用 `fail_get_many` / `stuck_cursor` 两个开关注入。
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeObservation:
    """一次 observation 创建的全部实参 + SDK 侧生成的 id。"""

    id: str
    trace_context: dict[str, str] | None = None
    name: str | None = None
    as_type: str | None = None
    input: Any = None
    output: Any = None
    metadata: Any = None
    version: str | None = None
    level: str | None = None
    status_message: str | None = None
    model: str | None = None
    usage_details: dict[str, int] | None = None

    def end(self) -> None:
        """真 SDK 是 OTEL span：不 end() 不导出。fake 记录在创建时，结束即空操作。"""


@dataclass
class FakeMeta:
    """v2 响应的分页 meta：只有 cursor。"""

    cursor: str | None = None


@dataclass
class FakeResponse:
    """`observations.get_many` 的 v2 响应形状：`data` + `meta.cursor`。"""

    data: list[FakeObservation] = field(default_factory=list)
    meta: FakeMeta = field(default_factory=FakeMeta)


class _FakeApi:
    """`client.api` 这一层：真实现里 observations 读口挂在它下面。"""

    def __init__(self, owner: FakeLangfuseClient) -> None:
        self.observations = _FakeObservationsApi(owner)


class _FakeObservationsApi:
    """Observations API v2 的假读口：按 trace_id 过滤、按小页游标分页。"""

    def __init__(self, owner: FakeLangfuseClient) -> None:
        self._owner = owner

    def get_many(self, **kwargs: Any) -> FakeResponse:
        if self._owner.fail_get_many is not None:
            raise self._owner.fail_get_many
        self._owner.get_many_calls.append(kwargs)

        rows = [
            o
            for o in self._owner.observations
            if (o.trace_context or {}).get("trace_id") == kwargs.get("trace_id")
        ]
        if self._owner.stuck_cursor is not None and kwargs.get("cursor"):
            # 卡死游标的病理服务：翻页请求永远回同一 cursor 且不再给新数据。
            return FakeResponse(data=[], meta=FakeMeta(cursor=self._owner.stuck_cursor))
        start = int(kwargs["cursor"]) if kwargs.get("cursor") else 0
        size = self._owner.page_size if self._owner.page_size else max(len(rows), 1)
        page = rows[start : start + size]
        next_index = start + size

        if self._owner.stuck_cursor is not None:
            cursor: str | None = self._owner.stuck_cursor
        elif next_index < len(rows):
            cursor = str(next_index)
        else:
            cursor = None
        return FakeResponse(data=page, meta=FakeMeta(cursor=cursor))


class FakeLangfuseClient:
    """记录全部创建调用的 SDK 假件；trace_id 按 seed 确定性生成。"""

    def __init__(self) -> None:
        self.observations: list[FakeObservation] = []
        self.get_many_calls: list[dict[str, Any]] = []
        self.flush_count = 0
        self.shutdown_count = 0
        self.fail_flush: Exception | None = None
        self.fail_get_many: Exception | None = None
        self.page_size: int | None = None
        self.stuck_cursor: str | None = None
        self.api = _FakeApi(self)

    # ---- SDK 写口：全部原样记录 ----

    def create_trace_id(self, *, seed: str) -> str:
        return "trace-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]

    def start_observation(self, **kwargs: Any) -> FakeObservation:
        return self._create(**kwargs)

    def start_as_current_observation(self, **kwargs: Any) -> Iterator[FakeObservation]:
        client = self

        @contextlib.contextmanager
        def _ctx() -> Iterator[FakeObservation]:
            yield client._create(**kwargs)

        return _ctx()

    def create_event(self, **kwargs: Any) -> FakeObservation:
        return self._create(**kwargs)

    def flush(self) -> None:
        self.flush_count += 1
        if self.fail_flush is not None:
            raise self.fail_flush

    def shutdown(self) -> None:
        self.shutdown_count += 1

    # ---- 测试辅助 ----

    def _create(self, **kwargs: Any) -> FakeObservation:
        observation = FakeObservation(id=f"obs-{len(self.observations) + 1}", **kwargs)
        self.observations.append(observation)
        return observation

    def observation_of(self, event_uuid: str) -> FakeObservation:
        """按本地事件 uuid 找到承载它的 observation（封套在 `output.pokemon_trace`）。"""
        matches = [
            o
            for o in self.observations
            if isinstance(o.output, dict)
            and isinstance(o.output.get("pokemon_trace"), dict)
            and o.output["pokemon_trace"]["uuid"] == event_uuid
        ]
        assert len(matches) == 1, f"event {event_uuid} 应恰有一个 observation：{len(matches)}"
        return matches[0]

    def observation_named(self, name: str) -> FakeObservation:
        matches = [o for o in self.observations if o.name == name]
        assert len(matches) == 1, f"name={name!r} 应恰有一个 observation：{len(matches)}"
        return matches[0]


__all__ = ["FakeLangfuseClient", "FakeObservation", "FakeResponse"]
