"""`MemoryIndexPort` 的默认实现：`MemoryIndexStore`——倒排索引 + 混合语义检索。

**只做四件事**：写入（uuid + 倒排索引 + 缓存好的检索向量，写穿落盘）、
按 uuid 点查、等值过滤检索（倒排索引取交集）、语义检索（内部调
`memory/retrieval.py::hybrid_retrieve`，对外不透明）。不理解 metadata/payload
装的是什么、不理解 text 说的是什么——分层原则见 AGENTS.md 四。

单文件 JSONL、启动时全量读回内存（跟 `EventObjectStore`/`KnowledgeStore` 同一
个取舍：这个项目现在的数据量级用不上真正的磁盘索引结构，全内存 + 写穿落盘
最简单、也最不容易出错）。`delete_many()` 之后重写整个文件——JSONL 追加写
不支持原地删除，量级小，重写一次的成本可以接受（跟 `EventObjectStore.truncate()`
同一个取舍）。
"""

from __future__ import annotations

import json
import pathlib
import uuid
from collections.abc import Sequence
from typing import Any

from pokemon_agent.interfaces import EmbeddingProvider, RerankerProvider
from pokemon_agent.memory.retrieval import hybrid_retrieve

_DEFAULT_DIR = pathlib.Path(__file__).resolve().parent / "records"
_DEFAULT_FILE = "records.jsonl"


class MemoryIndexStore:
    """`MemoryIndexPort` 的默认实现，见该接口的文档了解每个方法的契约。"""

    def __init__(
        self,
        embedder: EmbeddingProvider,
        reranker: RerankerProvider,
        directory: str | pathlib.Path | None = None,
    ) -> None:
        """接好检索用的两个模型 provider（依赖注入，不在这里自己 new）和落盘目录。

        目录里的历史记录在构造时全部读回内存——`self._records` 是存储本体，
        重启不丢；`self._inverted` 是从 `self._records` 派生的倒排索引，
        进程内维护，不落盘（重启时随 `self._records` 重建）。
        """
        self._embedder = embedder
        self._reranker = reranker
        self._dir = pathlib.Path(directory) if directory is not None else _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / _DEFAULT_FILE

        self._records: dict[str, dict[str, Any]] = {}
        self._inverted: dict[tuple[str, str], set[str]] = {}
        self._load_all()

    # ---- 写端 ----

    def put(self, metadata: dict[str, str], payload: dict, text: str = "") -> str:
        record_id = uuid.uuid4().hex
        vector = self._embedder.embed([text])[0] if text else None
        record: dict[str, Any] = {
            "uuid": record_id,
            "metadata": dict(metadata),
            "payload": payload,
            "text": text,
            "vector": vector,
        }
        self._append_line(record)
        self._index_record(record)
        return record_id

    def delete_many(self, uuids: Sequence[str]) -> None:
        changed = False
        for record_id in uuids:
            record = self._records.pop(record_id, None)
            if record is None:
                continue
            changed = True
            self._unindex_record(record)
        if changed:
            self._rewrite_file()

    # ---- 读端 ----

    def get(self, uuid: str) -> tuple[dict[str, str], dict] | None:  # noqa: A002 - 接口定的参数名
        record = self._records.get(uuid)
        if record is None:
            return None
        return dict(record["metadata"]), record["payload"]

    def get_many(self, uuids: Sequence[str]) -> list[tuple[str, dict[str, str], dict]]:
        out: list[tuple[str, dict[str, str], dict]] = []
        for record_id in uuids:
            record = self._records.get(record_id)
            if record is None:
                continue
            out.append((record_id, dict(record["metadata"]), record["payload"]))
        return out

    def filter(self, conditions: dict[str, str]) -> list[str]:
        if not conditions:
            return list(self._records.keys())
        sets = [self._inverted.get((field, value), set()) for field, value in conditions.items()]
        matched = set.intersection(*sets) if sets else set()
        return list(matched)

    def search(
        self, query: str, limit: int, conditions: dict[str, str] | None = None
    ) -> list[str]:
        assert query, "search() needs a non-empty query"
        assert limit > 0, f"search() needs limit > 0, got {limit}"

        candidate_ids = self.filter(conditions) if conditions else list(self._records.keys())
        candidate_ids = [rid for rid in candidate_ids if self._records[rid]["text"]]
        if not candidate_ids:
            return []

        texts = [self._records[rid]["text"] for rid in candidate_ids]
        vectors = [self._records[rid]["vector"] for rid in candidate_ids]
        ranked = hybrid_retrieve(
            query, texts, self._embedder, self._reranker, fuse_top_k=limit, document_vectors=vectors
        )
        return [candidate_ids[idx] for idx, _score in ranked]

    # ---- 索引维护（进程内，不落盘） ----

    def _index_record(self, record: dict[str, Any]) -> None:
        record_id = record["uuid"]
        for field, value in record["metadata"].items():
            self._inverted.setdefault((field, value), set()).add(record_id)
        self._records[record_id] = record

    def _unindex_record(self, record: dict[str, Any]) -> None:
        record_id = record["uuid"]
        for field, value in record["metadata"].items():
            key = (field, value)
            bucket = self._inverted.get(key)
            if bucket is None:
                continue
            bucket.discard(record_id)
            if not bucket:
                del self._inverted[key]

    # ---- 落盘 ----

    def _append_line(self, record: dict[str, Any]) -> None:
        with self._file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _rewrite_file(self) -> None:
        with self._file.open("w", encoding="utf-8") as fh:
            for record in self._records.values():
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _load_all(self) -> None:
        if not self._file.exists():
            return
        with self._file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # 最后一行被崩溃截断的残行是预期内的运行期情况，跳过不报错
                    # （同 EventObjectStore 的取舍）。
                    continue
                self._index_record(record)
