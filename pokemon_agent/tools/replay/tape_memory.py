"""`TapeMemory`：回放段里顶替记忆门面的**读**——按账上的 `refs` 直接取回当初读到的那几条。

不重跑检索（检索可能不确定，intent C8）：读口被调用时，对应的读账还没记，从磁带游标往后找
第一条同种的读账，把它的 `refs` 解析成自然键，经记忆的"按键取"读口（`fetch`）取回。
写照常真写（写的内容全由录下的输入算出），所以切换时记忆正好等于父线在目标 task 开局时。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolFetchReq,
    FromHarnessToMemoryToolQueryActMemoriesReq,
    FromHarnessToMemoryToolQueryActMemoriesResp,
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToMemoryToolQueryEpisodeSummariesResp,
    FromHarnessToMemoryToolQueryKnowledgeReq,
    FromHarnessToMemoryToolQueryKnowledgeResp,
    FromHarnessToMemoryToolQueryObjectEventsReq,
    FromHarnessToMemoryToolQueryObjectEventsResp,
    FromHarnessToMemoryToolQueryTaskMemoriesReq,
    FromHarnessToMemoryToolQueryTaskMemoriesResp,
)
from pokemon_agent.tools.interface import MemoryToolPort

from .errors import ReplayDiverged
from .tape import Tape, event_content


class TapeMemory:
    """`MemoryToolPort` 的回放版。切换前按 refs 取，切换后与写口、快照一律转给真件。"""

    def __init__(self, real: MemoryToolPort, tape: Tape) -> None:
        self._real = real
        self._tape = tape

    def query_act_memories(
        self, req: FromHarnessToMemoryToolQueryActMemoriesReq
    ) -> FromHarnessToMemoryToolQueryActMemoriesResp:
        if self._tape.switched:
            return self._real.query_act_memories(req)
        keys = [{"episode_id": ep, "step": step} for ep, step in self._refs("read_act_memory", 2)]
        acts = self._fetch("act", keys).acts
        return FromHarnessToMemoryToolQueryActMemoriesResp(entries=acts)

    def query_task_memories(
        self, req: FromHarnessToMemoryToolQueryTaskMemoriesReq
    ) -> FromHarnessToMemoryToolQueryTaskMemoriesResp:
        if self._tape.switched:
            return self._real.query_task_memories(req)
        keys = [{"episode_id": ep, "task_id": t} for ep, t in self._refs("read_task_memory", 2)]
        return FromHarnessToMemoryToolQueryTaskMemoriesResp(
            memories=self._fetch("task", keys).tasks
        )

    def query_episode_summaries(
        self, req: FromHarnessToMemoryToolQueryEpisodeSummariesReq
    ) -> FromHarnessToMemoryToolQueryEpisodeSummariesResp:
        if self._tape.switched:
            return self._real.query_episode_summaries(req)
        keys = [{"episode_id": ep} for (ep,) in self._refs("read_episode_memory", 1)]
        return FromHarnessToMemoryToolQueryEpisodeSummariesResp(
            summaries=self._fetch("episode", keys).episodes
        )

    def query_object_events(
        self, req: FromHarnessToMemoryToolQueryObjectEventsReq
    ) -> FromHarnessToMemoryToolQueryObjectEventsResp:
        if self._tape.switched:
            return self._real.query_object_events(req)
        keys = [
            {"episode_id": ep, "step": step, "place": place}
            for ep, step, place in self._refs("read_object_memory", 3)
        ]
        return FromHarnessToMemoryToolQueryObjectEventsResp(
            events=self._fetch("object", keys).objects
        )

    def query_knowledge(
        self, req: FromHarnessToMemoryToolQueryKnowledgeReq
    ) -> FromHarnessToMemoryToolQueryKnowledgeResp:
        if self._tape.switched:
            return self._real.query_knowledge(req)
        keys = [{"source": source} for (source,) in self._refs("read_knowledge", 1)]
        got = self._fetch("knowledge", keys)
        return FromHarnessToMemoryToolQueryKnowledgeResp(
            contents=got.knowledge_contents, sources=got.knowledge_sources
        )

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 —— 写口、快照、按键取照转真件
        return getattr(self._real, name)

    def _refs(self, kind: str, width: int) -> list[tuple[str, ...]]:
        """下一条 `kind` 读账的 refs，解析成 `width` 元组（`"(a, b)"` 或裸值）。"""
        refs = event_content(self._tape.peek({kind})).get("refs", [])
        return [_parse_ref(ref, width) for ref in refs]

    def _fetch(self, kind: str, keys: list[dict[str, str]]) -> Any:  # noqa: ANN401
        try:
            return self._real.fetch(FromHarnessToMemoryToolFetchReq(kind=kind, keys=keys))
        except LookupError as exc:
            raise ReplayDiverged(f"按账上的 refs 取 {kind} 记忆取不全：{exc}") from exc


def _parse_ref(ref: str, width: int) -> tuple[str, ...]:
    """`"(r1-ep1, 3)"` → `("r1-ep1", "3")`；`width == 1` 时 ref 就是裸值。"""
    if width == 1:
        return (ref,)
    parts = tuple(p.strip() for p in ref.strip().removeprefix("(").removesuffix(")").split(", "))
    assert len(parts) == width, f"ref {ref!r} 不是 {width} 段"
    return parts


__all__ = ["TapeMemory"]
