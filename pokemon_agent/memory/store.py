"""`MemoryStorePort` 的默认实现：`MemoryStore`——一条记录一个文件 + 每文件夹倒排索引。

**只做五件事**：写入（uuid 记录文件 + 倒排索引写穿）、按 uuid 点查、等值过滤检索
（倒排索引取交集）、语义检索（内部调 `memory/retrieval.py::hybrid_retrieve`，
对外不透明）、归档（文件搬走 + 摘出索引——checkpoint 恢复把作废分支搬进
`voided-<ts>/<kind>/`，走的就是这一条路径）。不理解 metadata/payload/text 是
什么、不理解 text 说的是什么——分层原则见 AGENTS.md 四。

## 落盘布局（每个 kind 一个实例、一个文件夹）

    memory/<kind>/
    ├── <uuid>.json        # json 类记录（step_memory / object_memory）：
    │                      #   {"uuid", "metadata", "payload", "text"}
    ├── <uuid>.md          # md 类记录（episode_memory / knowledge_memory）：
    │                      #   JSON frontmatter（uuid/metadata/payload）+ 正文（text）
    ├── index.json         # 本文件夹的倒排索引（派生物、写穿、可自愈重建）
    └── vectors.jsonl      # 语义检索向量缓存 sidecar（有 text 的文件夹才有意义）

## 索引是派生物，不是第二真相

真相永远是记录文件。`index.json` 在 put / archive 时随记录**写穿**（先写记录
文件、再原子重写索引）；启动时读索引后做一次**廉价对账**（文件集合 vs 索引
uuid 集合），不一致（崩溃窗口、手工动过目录、索引损坏）就地全量扫描该文件夹
重建并重写索引——自愈，不需要 WAL。

**全量重写而非增量**：json 无法原地改，而索引的更新单位是"字段桶"——一个
`(field, value)` 桶 put 时会加、archive 时会删，append-only 表达不了收紧；单
文件夹千级记录、索引几百 KB，重写成本可忽略，且全量重写幂等。与 0910 之前
那套"整文件重写"的取舍一致，只是触发频率从"删除时"变成了"每次写"。

**启动不读记录文件**（对账通过时）：filter 直接走 `index.json`，记录文件按 uuid
惰性读取——索引落盘换来的收益就是 filter 查询零扫描。只有语义检索召回候选时
才读文件取 text。
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid as uuid_module
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pokemon_agent.memory.retrieval import hybrid_retrieve

if TYPE_CHECKING:
    # 仅类型检查期依赖：运行期不 import interfaces（否则会连带拖进整层
    # schemas）。注入进来的 embedder/reranker 只需结构上满足 Protocol。
    from pokemon_agent.memory import EmbeddingProvider, RerankerProvider

# md 类 kind：记录是 frontmatter + 正文的 markdown；其余 kind 是整文件 JSON。
_MD_KINDS = frozenset({"episode_memory", "knowledge_memory"})

_KINDS = frozenset({"step_memory", "object_memory", *_MD_KINDS})
"""合法的 kind（= 子目录名 = collection 名，项目无关的概念）。"""

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _atomic_write_text(path: pathlib.Path, text: str) -> None:
    """临时文件 + rename 的原子写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class MemoryStore:
    """`MemoryStorePort` 的默认实现，见该接口的文档了解每个方法的契约。

    一个实例绑定一个 kind（= `memory/` 下的一个子文件夹）。全项目不按 run
    分层（0910 拍板）：`run_id` 是 metadata 里的普通过滤字段，跟 `map`、
    `scene` 完全对等，这一层不做任何特判。
    """

    def __init__(
        self,
        embedder: EmbeddingProvider,
        reranker: RerankerProvider,
        kind: str,
        root: str | pathlib.Path | None = None,
    ) -> None:
        """接好检索用的两个模型 provider（依赖注入，不在这里自己 new）、本实例
        负责的 kind，以及 `memory/` 根目录（缺省为仓库根级 `memory/`）。

        构造时读 `index.json` 并对账——对账失败就地全量扫描重建（见模块
        docstring"索引是派生物"）。记录文件本身**不读**，按 uuid 惰性读取。
        """
        assert kind in _KINDS, f"unknown kind {kind!r}, expected one of {sorted(_KINDS)}"
        self._embedder = embedder
        self._reranker = reranker
        self._kind = kind
        self._is_md = kind in _MD_KINDS
        base = pathlib.Path(root) if root is not None else _PROJECT_ROOT / "memory"
        self._dir = base / kind
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self._dir / "index.json"
        self._vectors_file = self._dir / "vectors.jsonl"

        # 内存态：倒排索引 field → value → uuid 集合 + 全量 uuid 集。
        # 记录正文不进内存，按 uuid 惰性读文件（见模块 docstring）。
        self._inverted: dict[str, dict[str, set[str]]] = {}
        self._uuids: set[str] = set()
        self._vectors: dict[str, list[float]] | None = None
        """向量缓存，**惰性加载**——只有语义检索真的用到时才读 vectors.jsonl。"""
        self._mtimes: dict[str, float] = {}
        """uuid → 记录文件 mtime（md 类的 `refresh_changed()` 用；随 index.json 持久化）。"""
        self._load_or_rebuild()

    @property
    def kind(self) -> str:
        """本实例绑定的 kind（= 子目录名 = collection 名）。"""
        return self._kind

    # ---- 写端 ----

    def put(self, metadata: dict[str, str], payload: dict, text: str = "") -> str:
        """写入一条记录：生成 uuid → 写记录文件（真相先落）→ 进内存索引 →
        重写本文件夹 index.json。

        后置条件：记录文件与索引同时可查；返回的 uuid 全局唯一、不带任何语义。
        """
        record_id = uuid_module.uuid4().hex
        self._write_record(record_id, dict(metadata), dict(payload), text)
        self._index_record(record_id, metadata)
        # 记下写入瞬间的 mtime：`refresh_changed()` 靠它区分"自己写的"与
        # "外部手工改的"。不记的话刚写完的记录会被判成 changed，白跑一遍 embed。
        self._mtimes[record_id] = self._record_path(record_id).stat().st_mtime
        self._save_index()
        if text and self._is_md:
            self._put_vector(record_id, text)
        return record_id

    def archive_many(self, uuids: Sequence[str], dest_dir: str | pathlib.Path) -> int:
        """把一批记录搬进 `dest_dir` 并摘出索引——**"让记录消失"的唯一路径**。

        `MemoryTool._trim_summaries()` 走的就是它（摘要超容量时按质量淘汰，搬进
        `memory/voided-<ts>/<kind>/`）。0910 拍板的"退出检索必须伴随物理移动"在这里
        兑现：不再有"摘索引但文件原地留"的中间态——那个状态在索引重建时无法还原，
        被丢弃的记录会复活。

        后置条件：每个存在的 uuid 的记录文件都已搬走、从检索世界消失；
        返回实际归档的条数。dest_dir 不随本实例的 kind 变——调用方
        （`MemoryTool`）自己拼（`voided-<ts>/<kind>/`）。
        """
        dest = pathlib.Path(dest_dir)
        moved = 0
        for record_id in uuids:
            if record_id not in self._uuids:
                continue
            src = self._record_path(record_id)
            if src.is_file():
                dest.mkdir(parents=True, exist_ok=True)
                os.replace(src, dest / src.name)
            self._unindex(record_id)
            moved += 1
        if moved:
            self._save_index()
        return moved

    def refresh_changed(self) -> None:
        """md 类记录的文件被直接编辑过（mtime 变了）就重读整条记录——正文重算
        向量、frontmatter 里的 metadata 重建倒排——保留"运营改 `.md` 不重启
        进程就生效"的性质（原 KnowledgeStore 的 mtime 增量重建逻辑的等价物）。
        正文与 metadata 都要刷新：只刷正文的话，改 `source` 这类过滤字段
        `filter()` 永远查不到新值。json 类是运行期写穿产物，直接 no-op。
        """
        if not self._is_md or not self._uuids:
            return
        changed = False
        for record_id in sorted(self._uuids):
            path = self._record_path(record_id)
            if not path.is_file():
                continue
            current = path.stat().st_mtime
            if current == self._mtimes.get(record_id):
                continue
            text, metadata, _payload = self._read_record(record_id)
            self._put_vector(record_id, text)
            # frontmatter 里的 metadata 也可能被外部改过：先摘旧桶、再按新
            # metadata 进桶，否则倒排索引永远停在重建那一刻。
            self._unindex(record_id)
            self._index_record(record_id, metadata)
            self._mtimes[record_id] = current
            changed = True
        if changed:
            self._save_index()

    # ---- 读端 ----

    def get(self, uuid: str) -> tuple[dict[str, str], dict, str] | None:  # noqa: A002 - 接口定的参数名
        """按 uuid 点查一条记录，返回 (metadata, payload, text)；不存在返回 None。"""
        if uuid not in self._uuids:
            return None
        text, metadata, payload = self._read_record(uuid)
        return metadata, payload, text

    def get_many(self, uuids: Sequence[str]) -> list[tuple[str, dict[str, str], dict, str]]:
        """批量点查，返回 [(uuid, metadata, payload, text), ...]；不存在的 uuid 跳过。"""
        out: list[tuple[str, dict[str, str], dict, str]] = []
        for record_id in uuids:
            if record_id not in self._uuids:
                continue
            text, metadata, payload = self._read_record(record_id)
            out.append((record_id, metadata, payload, text))
        return out

    def filter(self, conditions: dict[str, str]) -> list[str]:
        """等值过滤检索：每个 (field, value) 查倒排表拿候选集，取交集。

        conditions 为空返回全部 uuid。**不支持大小比较**——step 区间语义由
        调用方先等值筛小、再数值比较（ROADMAP 24 的分工）。
        """
        if not conditions:
            return list(self._uuids)
        sets = [
            set(self._inverted.get(field, {}).get(value, ())) for field, value in conditions.items()
        ]
        if any(not s for s in sets):
            return []
        return list(set.intersection(*sets))

    def search(self, query: str, limit: int, conditions: dict[str, str] | None = None) -> list[str]:
        """语义检索：先 filter 圈候选，再对有 text 的候选做混合检索排序。

        候选的向量从 sidecar 取；缺失（历史记录/外部写入）就现算并补进
        sidecar——与旧实现 `_episode_vector` 的惰性补算同一个道理。
        """
        candidate_ids = self.filter(conditions or {})
        ranked = self.rank(candidate_ids, query, fuse_top_k=max(limit * 3, 10))
        return [record_id for record_id, _score in ranked[:limit]]

    def rank(self, uuids: Sequence[str], query: str, fuse_top_k: int) -> list[tuple[str, float]]:
        """对一个**给定候选集**做混合检索排序，返回 [(uuid, 相关性分)] 降序。

        `search()` 是"filter 圈候选 + 截断"的便捷封装；`rank` 是底层原语——
        调用方（`MemoryTool` 的跨局摘要）要先把候选按自己的领域规则
        （场景通配匹配、质量粗筛）筛过一遍再进来，过滤逻辑不归这一层。
        没有 text 的候选直接跳过（语义检索看不见它）。
        """
        assert query, "rank() needs a non-empty query"
        assert fuse_top_k > 0, f"rank() needs fuse_top_k > 0, got {fuse_top_k}"

        texts: list[str] = []
        ids_with_text: list[str] = []
        for record_id in uuids:
            if record_id not in self._uuids:
                continue
            text, _, _payload = self._read_record(record_id)
            if text:
                texts.append(text)
                ids_with_text.append(record_id)
        if not ids_with_text:
            return []

        vectors = self._vectors or {}
        document_vectors: list[list[float] | None] = []
        for record_id, text in zip(ids_with_text, texts, strict=True):
            vec = vectors.get(record_id)
            if vec is None:
                vec = self._embedder.embed([text])[0]
                self._put_vector(record_id, text)
            document_vectors.append(vec)

        ranked = hybrid_retrieve(
            query,
            texts,
            self._embedder,
            self._reranker,
            fuse_top_k=fuse_top_k,
            document_vectors=document_vectors,
        )
        return [(ids_with_text[idx], score) for idx, score in ranked]

    def count(self) -> int:
        """当前在索引里的记录条数（不含已归档的）。"""
        return len(self._uuids)

    # ---- 记录文件（真相层） ----

    def _record_path(self, record_id: str) -> pathlib.Path:
        ext = "md" if self._is_md else "json"
        return self._dir / f"{record_id}.{ext}"

    def _write_record(
        self, record_id: str, metadata: dict[str, str], payload: dict, text: str
    ) -> None:
        if self._is_md:
            frontmatter = json.dumps(
                {"uuid": record_id, "metadata": metadata, "payload": payload},
                ensure_ascii=False,
                indent=2,
            )
            content = f"---\n{frontmatter}\n---\n{text}\n"
        else:
            content = json.dumps(
                {"uuid": record_id, "metadata": metadata, "payload": payload, "text": text},
                ensure_ascii=False,
            )
        _atomic_write_text(self._record_path(record_id), content)

    def _read_record(self, record_id: str) -> tuple[str, dict[str, str], dict]:
        """读一条记录，返回 (text, metadata, payload)。文件缺失 = 索引陈旧，
        当作不存在处理（调用方的 `uuid not in self._uuids` 分支已拦住大多数；
        这里兜住"对账后文件被外部动过"的残余窗口）。"""
        path = self._record_path(record_id)
        if not path.is_file():
            self._unindex(record_id)
            return "", {}, {}
        raw = path.read_text(encoding="utf-8")
        if self._is_md:
            meta = self._parse_frontmatter(raw)
            body = self._parse_body(raw)
            return body, dict(meta.get("metadata", {})), dict(meta.get("payload", {}))
        data: dict[str, Any] = json.loads(raw)
        return (
            str(data.get("text", "")),
            dict(data.get("metadata", {})),
            dict(data.get("payload", {})),
        )

    @staticmethod
    def _parse_frontmatter(raw: str) -> dict[str, Any]:
        assert raw.startswith("---\n"), "md record must start with frontmatter"
        end = raw.find("\n---\n", 4)
        assert end >= 0, "md record frontmatter not terminated"
        return json.loads(raw[4:end])

    @staticmethod
    def _parse_body(raw: str) -> str:
        end = raw.find("\n---\n", 4)
        return raw[end + 5 :].strip() if end >= 0 else ""

    # ---- 索引维护 ----

    def _index_record(self, record_id: str, metadata: dict[str, str]) -> None:
        for field, value in metadata.items():
            self._inverted.setdefault(field, {}).setdefault(value, set()).add(record_id)
        self._uuids.add(record_id)

    def _unindex(self, record_id: str) -> None:
        """从倒排表、uuid 集合与 mtime 表里摘掉一条记录（不动文件）。"""
        for buckets in self._inverted.values():
            for bucket in buckets.values():
                bucket.discard(record_id)
        # 清空桶，防止空桶无限累积
        for field in list(self._inverted):
            self._inverted[field] = {
                value: ids for value, ids in self._inverted[field].items() if ids
            }
            if not self._inverted[field]:
                del self._inverted[field]
        self._uuids.discard(record_id)
        self._mtimes.pop(record_id, None)

    # ---- index.json：派生物，写穿 + 自愈 ----

    def _save_index(self) -> None:
        """全量重写 index.json：uuid 列表排序，保证同样内容写出同样字节。"""
        doc = {
            "kind": self._kind,
            "count": len(self._uuids),
            "inverted": {
                field: {value: sorted(ids) for value, ids in sorted(buckets.items())}
                for field, buckets in sorted(self._inverted.items())
            },
            "mtimes": {k: self._mtimes[k] for k in sorted(self._mtimes) if k in self._uuids},
        }
        _atomic_write_text(self._index_file, json.dumps(doc, ensure_ascii=False, indent=2))

    def _load_or_rebuild(self) -> None:
        """启动：读 index.json → 廉价对账（文件集合 vs 索引 uuid 集合）→
        不一致就地全量扫描重建。对账通过时不读任何记录文件。"""
        doc = self._load_index_file()
        ext = "md" if self._is_md else "json"
        files = {p.stem for p in self._dir.glob(f"*.{ext}") if p.stem != "index"}
        indexed = self._uuids_from_doc(doc)
        if files == indexed:
            self._inverted = {
                field: {value: set(ids) for value, ids in buckets.items()}
                for field, buckets in doc.get("inverted", {}).items()
            }
            self._uuids = indexed
            self._mtimes = dict(doc.get("mtimes", {}))
            return
        # 对账失败：全量扫描重建（真相是记录文件，索引只是派生物）。
        self._inverted = {}
        self._uuids = set()
        self._mtimes = {}
        for record_id in sorted(files):
            _, metadata, _payload = self._read_record(record_id)
            self._index_record(record_id, metadata)
            self._mtimes[record_id] = self._record_path(record_id).stat().st_mtime
        self._save_index()

    def _load_index_file(self) -> dict[str, Any]:
        if not self._index_file.is_file():
            return {}
        try:
            return json.loads(self._index_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}  # 索引损坏 = 派生物受损，走全量重建，不崩

    def _uuids_from_doc(self, doc: dict[str, Any]) -> set[str]:
        out: set[str] = set()
        for buckets in doc.get("inverted", {}).values():
            for ids in buckets.values():
                out.update(ids)
        return out

    # ---- 向量 sidecar ----

    def _load_vectors(self) -> dict[str, list[float]]:
        if self._vectors is None:
            vectors: dict[str, list[float]] = {}
            if self._vectors_file.is_file():
                for line in self._vectors_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 崩溃残行，预期内跳过
                    vectors[row["uuid"]] = row["vector"]
            self._vectors = vectors
        return self._vectors

    def _put_vector(self, record_id: str, text: str) -> None:
        """算一条向量并追加写进 sidecar（最后一行为准，重复行无害）。"""
        if not text:
            return
        vector = self._embedder.embed([text])[0]
        self._load_vectors()[record_id] = vector
        with self._vectors_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"uuid": record_id, "vector": vector}, ensure_ascii=False) + "\n")
