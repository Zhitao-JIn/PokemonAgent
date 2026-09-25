"""`build_saver`：造 LangGraph 的 sqlite saver——图状态的持久化后端，连同反序列化白名单一起装好。"""

from __future__ import annotations

import sqlite3
import types
import typing
from enum import Enum
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel

from ..episode.episode_state import EpisodeRunState
from ..run.run_state import RunState
from ..task.task_state import TaskState

DB_FILENAME = "langgraph.sqlite"
"""图状态库在存档根下的文件名。"""


def state_types(*roots: type[BaseModel]) -> list[tuple[str, str]]:
    """从状态模型出发，沿字段类型递归收集全部 Pydantic 模型与枚举，返回 `(模块, 类名)` 列表。

    saver 的 `allowed_msgpack_modules` 只认逐个的 `(模块路径, 类名)`，按包前缀登记无效
    （`docs/checkpoint/p0-findings.md` K-d）；由状态模型推导，模型改了列表自动跟着变。
    后置条件：每个根自身都在结果里；结果无重复，按收集顺序排列。
    """
    seen: set[type] = set()
    found: list[tuple[str, str]] = []

    def visit(tp: object) -> None:
        # 步骤 1：泛型与联合类型拆开逐个看（list[X]、X | None、dict[K, V]、Annotated[X, …]）。
        if typing.get_origin(tp) is not None or isinstance(tp, types.UnionType):
            for arg in typing.get_args(tp):
                visit(arg)
            return
        # 步骤 2：模型与枚举登记；模型再沿字段往下走。
        if not isinstance(tp, type) or tp in seen:
            return
        if issubclass(tp, BaseModel):
            seen.add(tp)
            found.append((tp.__module__, tp.__name__))
            for field in tp.model_fields.values():
                visit(field.annotation)
        elif issubclass(tp, Enum):
            seen.add(tp)
            found.append((tp.__module__, tp.__name__))

    for root in roots:
        visit(root)
    assert all((r.__module__, r.__name__) in found for r in roots)
    return found


def build_saver(checkpoint_root: str | Path) -> SqliteSaver:
    """在 `<checkpoint_root>/langgraph.sqlite` 上造一个 `SqliteSaver`，白名单覆盖三种状态模型。

    连接允许跨线程使用：LangGraph 在自己的线程池里调用 saver。
    前置条件：`checkpoint_root` 非空；目录不存在时创建。
    """
    root = Path(checkpoint_root)
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / DB_FILENAME, check_same_thread=False)
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=state_types(RunState, EpisodeRunState, TaskState)
    )
    saver = SqliteSaver(conn, serde=serde)
    saver.setup()
    return saver


__all__ = ["DB_FILENAME", "build_saver", "state_types"]
