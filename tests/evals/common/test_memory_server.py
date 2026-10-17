"""clear_memory：以空 zip 还原清空共享库；不带 admin 时错误向上传递。"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doubles.memory_server import act, memory_server_context, recall
from _doubles.memory_server import remote as remote

from evals.common.memory_server import clear_memory
from pokemon_agent.mcpclient.memory_tool import MemoryAdminDisabled
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeRecord,
    FromHarnessToMemoryToolMemorizeReq,
)


def test_clear_memory_empties_the_library(remote) -> None:  # noqa: ANN001
    """先写若干条，clear 后按同条件 recall 为空。"""
    _, tool = remote
    tool.memorize(
        FromHarnessToMemoryToolMemorizeReq(
            records=[
                FromHarnessToMemoryToolMemorizeRecord(**act(0)),
                FromHarnessToMemoryToolMemorizeRecord(**act(1)),
            ]
        )
    )
    assert recall(tool), "写入后应能读回"

    clear_memory(tool)

    assert recall(tool) == []


def test_clear_memory_requires_admin(tmp_path: Path) -> None:
    """不带 --enable-admin 的 server → restore 被拒，错误向上传递。"""
    with (
        memory_server_context(tmp_path / "server", tmp_path / "client", enable_admin=False) as (
            _,
            tool,
        ),
        pytest.raises(MemoryAdminDisabled),
    ):
        clear_memory(tool)
