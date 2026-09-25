"""`FromHarnessToMemoryToolFetchReq`：按自然键**直接取**记录（不检索、不排序）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FetchKind = Literal["act", "task", "episode", "object", "knowledge"]


class FromHarnessToMemoryToolFetchReq(BaseModel):
    """**按键取**：给出一串自然键，按给定顺序取回对应记录。

    每种记录的自然键（都是写入时已落的元数据字段）：

    | kind | 键字段 |
    |---|---|
    | `act` | `episode_id`、`step` |
    | `task` | `episode_id`、`task_id` |
    | `episode` | `episode_id` |
    | `object` | `episode_id`、`step`、`place` |
    | `knowledge` | `source` |

    同一个键出现 n 次就取回 n 条（同一格同一步可以有多条对象事件）。
    """

    kind: FetchKind = Field(description="哪一族记录")
    keys: list[dict[str, str]] = Field(description="自然键，字段见上表；值一律字符串")
