"""trace 自己的事件实现：`_Event`。

**为什么必须有一个具体类**：`Event`（`trace/interface/event.py`）是协议，
它声明不了"怎么构造"。而 `store.py` 真的要构造一条事件——落盘前 `new` 一个、
扫盘时把磁盘上的 json 解析成一个。所以需要这一份**trace 私有的**实现。

**六个字段，一个都不多**（0914 封套改造）：

| 组 | 字段 | 谁填 |
|---|---|---|
| 封套 | `uuid`/`kind`/`type`/`ts` | `uuid`/`ts` 归 `store.py`；`kind`/`type` 由调用方给 |
| 标签 | `meta` | 调用方给（**JSON 字符串**）——harness 自报的签名信息 |
| 正文 | `content` | 调用方给（**JSON 字符串**）——这笔账的本体 |

`uuid` 是文件名、`ts` 是写入时刻，两者都由 `store.py` 在落盘那一刻盖。

删掉的四件：`event_id`（唯一读方是随 `frame_png` 一起下线的"按 id 取单条"）、
`schema_version`（恒 `5`、零读方、两份副本要人工同步）、`frame_png`（画面真源
改到 `memory/step_memory/`）、顶层 `run_id`/`episode_id`/`step`（搬进 `meta`）。

**排序改看 `(ts, uuid)`**（原 `event_id` 的活）：`ts` 从死字段变成排序键——
`time.time()` 在 3.12 是百纳秒级，同值几乎不可能，真同值了还有 `uuid` 兜底。

**`extra="allow"` 是这份契约的关键一半**：盘上可能躺着改形之前的老 json
（带 `event_id`/`schema_version`/`payload`/`frame_png` 那套）。解析时它们不能丢
——读端要能一眼看出"这批数据是旧格式"。`allow` 让它们挂在 `model_extra` 上随行。

**不进任何 `__all__`**：外部一律通过 `Event` 协议说话，本类只服务
`trace/store.py`（它 `from .datastore.event import _Event`）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Event(BaseModel):
    """trace 的一条事件。字段与 `trace/interface/event.py::Event` 一一对应。

    **两个 JSON 键收进来就已经是字符串**（`meta` / `content`）——序列化在
    `store.py` 做，本类只管搬。
    """

    model_config = ConfigDict(extra="allow")

    uuid: str = Field(description="本次事件的唯一标识（= 文件名），落盘那一刻由 store 盖上")
    kind: str = Field(description="账名（裸 str，取值由声明方定义）")
    type: str = Field(description="事件种类（裸 str，取值由声明方定义）")
    ts: float = Field(description="Unix 时间戳（秒），写入那一刻由 store 盖上")
    meta: str = Field(default="{}", description="签名信息的 JSON 字符串")
    content: str = Field(default="{}", description="账本体的 JSON 字符串")
