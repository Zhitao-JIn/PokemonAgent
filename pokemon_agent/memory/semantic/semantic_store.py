"""语义记忆的实现：一格物体交互事件流 + 从目录读通用先验。

**两个类住一个文件是刻意的**——与 `memory/episode/episode_store.py`
（`FileEpisodeMemoryStore`）对称：每类记忆只留两个文件。合并的是文件不是类：
object 半身是 agent 自己探索出来、可写的事件流；knowledge 半身不挂坐标、
运营维护、只读——两个类的形状完全不同，各自独立，不共享状态。

## EventObjectStore：一格物体交互事件的纯日志

**memory 不理解游戏**（分层原则见 AGENTS.md 四）：这里只做三件事——追加
（写穿：落盘与内存索引同时生效）、按格/按图过滤直返事件、恢复时的截断。
没有物化视图、没有折叠、没有派生字段；内存里的 `self._events` 是存储本体
（进程内的那份日志），不是缓存出来的视图。渲染成 prompt 文本在 `prompts/`
（组装辅助），"这扇门通向哪"这类问题由消费方对事件现算。

按局分文件（`ep-{id}.jsonl`）：checkpoint 恢复时的截断只影响一局，
重写一个文件就够了。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Any

from pydantic import TypeAdapter, ValidationError

from pokemon_agent.schemas.datastore import ObjectFactEvent
from pokemon_agent.schemas.domain import PlaceInWorld

_DEFAULT_EVENTS_DIR = pathlib.Path(__file__).resolve().parent / "object_events"
_DEFAULT_KNOWLEDGE_DIR = pathlib.Path(__file__).resolve().parent / "knowledge"


def _safe_episode_id(episode_id: str) -> str:
    """把 episode_id 压成文件名安全的一段；压完为空时落 `unknown`。"""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_-") or "unknown"


class EventObjectStore:
    """`SemanticObjectStore` 的默认实现：按局分文件的 JSONL 事件日志。"""

    def __init__(self, directory: str | pathlib.Path | None = None) -> None:
        """接好事件目录；不传则用包内 `semantic/object_events/`。

        目录里的历史事件在构造时全部读回内存（`self._events` 就是存储本体，
        重启不丢——写穿保证盘上永远不落后于内存）。JSONL 逐行一条事件；
        最后一行被崩溃截断的残行是预期内的运行期情况，读不出来就跳过。
        """
        self._dir = pathlib.Path(directory) if directory is not None else _DEFAULT_EVENTS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._events: list[ObjectFactEvent] = []
        self._max_step: dict[str, int] = {}
        """`episode_id → 该局事件的最大 step`；`append` 单调前置的依据。"""
        self._load_all()

    # ---- 读端 ----

    def query(self, place: PlaceInWorld) -> list[ObjectFactEvent]:
        """取这一格的全部交互事件，按 step 升序（写入顺序稳定排序）。"""
        events = [e for e in self._events if e.place.key == place.key]
        return sorted(events, key=lambda e: e.step)

    def query_range(
        self, episode_id: str, step_min: int, step_max: int
    ) -> list[ObjectFactEvent]:
        """取这一局 `[step_min, step_max]` 区间的交互事件（checkpoint 归档取废弃段用）。"""
        events = [
            e
            for e in self._events
            if e.episode_id == episode_id and step_min <= e.step <= step_max
        ]
        return sorted(events, key=lambda e: e.step)

    def query_map(self, map_id: int, before_step: int | None = None) -> list[ObjectFactEvent]:
        """取这张地图上的全部交互事件，按 step 升序。

        `before_step` 非空时只返回 step 严格小于它的（"检索不读未来"）。
        """
        events = [
            e
            for e in self._events
            if e.place.map_id == map_id and (before_step is None or e.step < before_step)
        ]
        return sorted(events, key=lambda e: e.step)

    # ---- 写端 ----

    def append(self, events: list[ObjectFactEvent]) -> None:
        """追加一批事件：逐条先写穿落盘，再进内存索引。

        前置条件：每个事件的 step ≥ 其所在局文件里已有的最大 step
            （等于容忍崩溃窗口的重复，恢复时的截断负责清理）；
            同一批内同局事件也必须单调不减。
        后置条件：落盘与内存同时生效——崩溃最多丢"没写完的那一行"，
            盘上永远不落后于内存。
        """
        if not events:
            return
        by_episode: dict[str, list[ObjectFactEvent]] = {}
        for event in events:
            assert event.step >= self._max_step.get(event.episode_id, 0), (
                f"append got a stale event: episode {event.episode_id} "
                f"step {event.step} < max {self._max_step.get(event.episode_id, 0)}"
            )
            by_episode.setdefault(event.episode_id, []).append(event)

        # 步骤 1：逐局写穿（append 模式逐行追加）。
        for episode_id, batch in by_episode.items():
            with self._file(episode_id).open("a", encoding="utf-8") as fh:
                for event in batch:
                    fh.write(event.model_dump_json() + "\n")

        # 步骤 2：内存索引。崩溃发生在两步之间时，重启会从盘上重读——
        # 盘上是真相，内存只是同一份的进程内副本。
        for event in events:
            self._events.append(event)
            self._max_step[event.episode_id] = max(
                self._max_step.get(event.episode_id, 0), event.step
            )

    def truncate(self, episode_id: str, step: int) -> None:
        """把这一局 step 大于 `step` 的事件全部删掉（checkpoint 恢复的截断）。

        键控幂等：没有超界的记录就什么都不做；删完把该局文件原子重写
        （临时文件 + rename，不留半截文件）。后置条件由断言执行：
        重算后该局不存在 step > step 的事件。
        """
        survivors = [e for e in self._events if not (e.episode_id == episode_id and e.step > step)]
        removed = len(self._events) - len(survivors)
        if removed == 0:
            return
        kept = [e for e in self._events if e.episode_id == episode_id and e.step <= step]
        target = self._file(episode_id)
        tmp = target.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for event in kept:
                fh.write(event.model_dump_json() + "\n")
        os.replace(tmp, target)
        self._events = survivors
        self._max_step[episode_id] = max((e.step for e in kept), default=0)

    # ---- 内部 ----

    def _file(self, episode_id: str) -> pathlib.Path:
        """这一局的事件文件路径：按局一个 JSONL，截断只重写一个文件。"""
        return self._dir / f"ep-{_safe_episode_id(episode_id)}.jsonl"

    def _load_all(self) -> None:
        """启动时扫描目录，把全部事件读回内存。

        逐行解析，读不出来的行跳过——那只能是进程崩溃截断的残行
        （写穿是先盘后序，盘上内容永远自洽到最后一行完整处），
        属于预期内的运行期情况，不是这里要修的错。
        """
        adapter = TypeAdapter(ObjectFactEvent)
        for path in sorted(self._dir.glob("ep-*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    data: Any = json.loads(line)
                    event = adapter.validate_python(data)
                except (json.JSONDecodeError, ValidationError):
                    continue
                self._events.append(event)
                self._max_step[event.episode_id] = max(
                    self._max_step.get(event.episode_id, 0), event.step
                )


class KnowledgeStore:
    """知识库的存储：从一个目录读运营维护的 md 分片。只读，不认游戏规则。"""

    def __init__(self, directory: str | pathlib.Path | None = None) -> None:
        """接好知识库目录；不传则用默认的 `semantic/knowledge/`。"""
        self._dir = pathlib.Path(directory) if directory is not None else _DEFAULT_KNOWLEDGE_DIR

    def chunks(self) -> list[tuple[str, str]]:
        """一次读盘返回 `[(文件名, 正文)]`，只含非空 `.md`，按文件名排序。

        不在文件内部按段落拆分：同一文件中的标题、说明和例子共同构成一个
        知识主题，保留在同一个检索单元里，避免召回段落时丢失上下文。

        后置条件：目录下没有任何 `.md` 文件、或全部文件都是空文件时返回空列表——
            调用方（`MemoryTool.query_knowledge`）据此知道"没有知识可检索"，
            不必特殊处理"检索了但库是空的"这种情况，两者应该是同一件事。
        """
        files = sorted(p for p in self._dir.glob("*.md"))
        return [(f.name, text) for f in files if (text := f.read_text(encoding="utf-8").strip())]

    def mtime(self) -> float:
        """知识库目录下全部 `.md` 文件里最新的修改时间；没有文件时返回 0.0。

        `MemoryTool` 用它判断"要不要重新算一遍知识片段的 embedding"——
            embedding 现算一次有成本，但知识库内容会被运营编辑，值得按
            "文件有没有变过"决定要不要重新读取文件并重算 embedding。
        """
        files = list(self._dir.glob("*.md"))
        if not files:
            return 0.0
        return max(f.stat().st_mtime for f in files)
