"""`TapeTrace`：回放段里顶替 trace 门面——不落盘，每一笔与磁带比对；读账返回"本该已写出的"。

走到目标 task 的 `task_start` 那一笔时切换（`Tape.switch`）：切换钩子里恢复路径先记
`checkpoint_restore`（新执行线第一条账），随后这笔 `task_start` 照常落盘，此后一切照常。
"""

from __future__ import annotations

import json
from typing import Any

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import TraceEvent
from pokemon_agent.tools.interface import TraceToolPort
from pokemon_agent.tools.trace import render_request

from .tape import MODEL_CALL_TYPE, NOT_COMPARED_KINDS, Tape


class TapeTrace:
    """`TraceToolPort` 的回放版。切换前比对不落盘，切换后原样转给真件。"""

    def __init__(self, real: TraceToolPort, tape: Tape) -> None:
        self._real = real
        self._tape = tape

    def append(self, req: FromHarnessToTraceToolAppendReq) -> None:
        """切换前：渲染后与磁带逐条比对（不落盘）；碰到目标 `task_start` 就切换再落盘。"""
        if self._tape.switched:
            self._real.append(req)
            return
        if req.kind == TraceKind.TASK_START and self._is_target(req.meta):
            self._tape.switch(dict(req.meta))
            self._real.append(req)
            return
        for rendered in render_request(req):
            if rendered.type == MODEL_CALL_TYPE or str(rendered.kind) in NOT_COMPARED_KINDS:
                continue
            self._tape.check(str(rendered.kind), dict(req.meta), rendered.content)

    def read_events(self, meta: dict[str, Any] | None = None) -> list[TraceEvent]:
        """切换前：返回磁带上已放过的账（本该已写出的那些）按 `meta` 交集筛；切换后照常读。"""
        if self._tape.switched:
            return self._real.read_events(meta)
        wanted = meta or {}
        return [
            e
            for e in self._tape.played()
            if all(json.loads(e.meta).get(k) == v for k, v in wanted.items())
        ]

    def _is_target(self, meta: dict[str, Any]) -> bool:
        return (
            meta.get("episode_id") == self._tape.target_episode
            and meta.get("task_id") == self._tape.target_task
        )


__all__ = ["TapeTrace"]
