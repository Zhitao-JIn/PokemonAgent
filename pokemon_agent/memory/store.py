"""`MemoryStorePort` 的默认实现：`LocalMemoryStore`——一条记录一个文件 + 每文件夹倒排索引。

**只做六件事**：写入（uuid 记录文件 + 倒排索引写穿）、按 uuid 点查、等值过滤检索
（倒排索引取交集）、语义检索（内部调 `memory/retrieval.py::hybrid_retrieve`，
对外不透明）、删除（摘出索引 + unlink）、快照（打包整个记忆根成 zip / 用 zip
还原回来）。不理解 metadata/payload/text 是什么、不理解 text 说的是什么——分层
原则见 AGENTS.md 四。

## 落盘布局（整个记忆库一个根，四族各占一个子文件夹）

    memory/
    ├── step_memory/       # 每族一个 LocalMemoryStore 实例
    │   ├── <uuid>.json    # json 类记录（step_memory / object_memory）：
    │   │                  #   {"uuid", "metadata", "payload", "text"}
    │   ├── <uuid>.md      # md 类记录（episode_memory / knowledge_memory）：
    │   │                  #   JSON frontmatter（uuid/metadata/payload）+ 正文（text）
    │   ├── index.json     # 本文件夹的倒排索引（派生物、写穿、可自愈重建）
    │   └── vectors.jsonl  # 语义检索向量缓存 sidecar（有 text 的文件夹才有意义）
    ├── object_memory/     # 同上
    ├── episode_memory/    # 同上
    ├── knowledge_memory/  # 同上
    └── snapshots/         # 快照 zip（0916，由 memory 自己管理，harness 只给名字）

## 索引是派生物，不是第二真相

真相永远是记录文件。`index.json` 在 put / 删除时随记录**写穿**（先写记录
文件、再原子重写索引）；启动时读索引后做一次**廉价对账**（文件集合 vs 索引
uuid 集合），不一致（崩溃窗口、手工动过目录、索引损坏）就地全量扫描该文件夹
重建并重写索引——自愈，不需要 WAL。

**全量重写而非增量**：json 无法原地改，而索引的更新单位是"字段桶"——一个
`(field, value)` 桶 put 时会加、删除时会删，append-only 表达不了收紧；单
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
import shutil
import tempfile
import uuid as uuid_module
import zipfile
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pokemon_agent.memory.retrieval import hybrid_retrieve

if TYPE_CHECKING:
    # 仅类型检查期依赖：运行期不 import interfaces（否则会连带拖进整层
    # schemas）。注入进来的 embedder/reranker 只需结构上满足 Protocol。
    from pokemon_agent.memory import EmbeddingProviderPort, RerankerProviderPort

# md 类 kind：记录是 frontmatter + 正文的 markdown；其余 kind 是整文件 JSON。
_MD_KINDS = frozenset({"episode_memory", "knowledge_memory"})

_KINDS = frozenset({"step_memory", "object_memory", *_MD_KINDS})
"""合法的 kind（= 子目录名 = collection 名，项目无关的概念）。"""

SNAPSHOTS_DIRNAME = "snapshots"
"""快照 zip 在记忆根下的存放子目录名（0916）。**由本模块管**，harness 只给 zip 名。"""


def _default_root() -> pathlib.Path:
    """缺省落盘根：**进程启动目录**下的 `memory/`（0916 起）。

    memory 是独立第三方模块，"项目仓库根在哪"不是它该知道的事——曾经的
    `Path(__file__)` 回溯仓库根已删，缺省改为启动时问一次 `cwd`。
    """
    return pathlib.Path.cwd() / "memory"


def _atomic_write_text(path: pathlib.Path, text: str) -> None:
    """临时文件 + rename 的原子写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class LocalMemoryStore:
    """`MemoryStorePort` 的默认实现，见该接口的文档了解每个方法的契约。

    一个实例绑定一个 kind（= `memory/` 下的一个子文件夹）。全项目不按 run
    分层（0910 拍板）：`run_id` 是 metadata 里的普通过滤字段，跟 `map`、
    `scene` 完全对等，这一层不做任何特判。
    """

    def __init__(
        self,
        embedder: EmbeddingProviderPort,
        reranker: RerankerProviderPort,
        kind: str,
        root: str | pathlib.Path | None = None,
    ) -> None:
        """接好检索用的两个模型 provider（依赖注入，不在这里自己 new）、本实例
        负责的 kind，以及 `memory/` 根目录（缺省为启动目录下的 `memory/`）。

        构造时读 `index.json` 并对账——对账失败就地全量扫描重建（见模块
        docstring"索引是派生物"）。记录文件本身**不读**，按 uuid 惰性读取。
        """
        assert kind in _KINDS, f"unknown kind {kind!r}, expected one of {sorted(_KINDS)}"
        self._embedder = embedder
        self._reranker = reranker
        self._kind = kind
        self._is_md = kind in _MD_KINDS
        base = pathlib.Path(root) if root is not None else _default_root()
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

    def delete_many(self, uuids: Sequence[str]) -> int:
        """把一批记录**删掉**（摘出索引 + unlink 记录文件）——"让记录消失"的唯一路径。

        `MemoryTool._trim_summaries()` 走的就是它（摘要超容量时按质量淘汰）。
        **0916 起不再有"归档"**：原先的 `archive_many` 把文件搬进
        `memory/voided-<ts>/<kind>/` 留档，换成快照（`snapshot()` / `restore()`）之后
        那套中间态没有了意义——要留档就在淘汰之前先拍一张快照，淘汰本身该是干脆的。

        走这条路之后，被删的记录会在**下次启动**时从向量 sidecar 里自然消失：
        `_load_vectors` 只认活着的 uuid（见 `_vectors_for`）。

        后置条件：每个存在的 uuid 的记录文件都已 unlink、从检索世界消失；
        返回实际删掉的条数。不存在的 uuid 跳过、不报错。
        """
        deleted = 0
        for record_id in uuids:
            if record_id not in self._uuids:
                continue
            self._record_path(record_id).unlink(missing_ok=True)
            self._unindex(record_id)
            deleted += 1
        if deleted:
            self._save_index()
        return deleted

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
        """当前在索引里的记录条数（不含已删的）。"""
        return len(self._uuids)

    def reload(self) -> None:
        """把内存态（倒排索引 / uuid 集合 / mtime / 向量缓存）从盘上重新读一遍。

        唯一调用方是 `MemoryTool.restore_memory()`：恢复是**整根覆盖**，而每个
        实例只刷新自己那一个 kind 的内存态，另外三个得由调用方挨个叫一下。
        平时不需要它——`put` / `delete_many` 都是写穿（内存态与盘上同步）。

        代价与构造期一样：对账通过时只读 `index.json`，不读记录文件。
        """
        self._vectors = None
        self._load_or_rebuild()

    # ---- 快照（0916：zip 由 memory 自己管，调用方只给名字） ----

    def snapshot(self, name: str) -> pathlib.Path:
        """把**整个记忆根**打包成一个 zip，返回 zip 路径（同名覆盖）。

        **打的是整个根，不是本实例的 kind**：四个 store 共享一个 `memory/` 根，
        "这一族"和"整个库"在快照这个语义下不是一回事——调用方要的是一份能整体
        还原的存档，不是一族的碎片。所以任意一个 store 上的 `snapshot()` 拿到活的
        都一样（幂等）。

        zip 落在 `<根>/snapshots/<name>.zip`——**路径由本层决定**（harness 只给
        `name`）。

        **先在根外面打，再挪进来**（0916 修）：zip 的落点在根**里面**，而 zip
        正被写入时它自己也在根里——直接 `make_archive(root_dir=root)` 会把一个
        边写边长的 zip 当成待打包文件读进去，自我引用到卡死（真机 2.5 分钟没
        出来，faulthandler 卡在 `zipfile.write`）。所以先在系统临时目录把 zip
        打好（并顺手排除 `snapshots/`，否则每次快照都把上一次的 zip 套进来），
        最后 `os.replace` 挪到目标位置——跨盘时 replace 会失败，用
        `shutil.move` 兜底。

        前置条件：`name` 非空、不含路径分隔符（它只是文件名，不是路径）。
        后置条件：zip 里每个 kind 子目录的记录文件与 `index.json` 都在、且不含
            `snapshots/`；返回的路径已存在于盘上。
        """
        assert name, "snapshot() needs a non-empty name"
        assert pathlib.PurePath(name).name == name, (
            f"snapshot() 的 name 只能是文件名，不能带路径分隔符：{name!r}"
        )
        root = self._dir.parent
        dest_dir = root / SNAPSHOTS_DIRNAME
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{name}.zip"

        # 在根**外面**打：临时目录里造一个 zip，条目路径写成相对记忆根的
        # （`step_memory/xxx.json`），恢复时直接解回根下、不必剥前缀。
        with tempfile.TemporaryDirectory() as staging:
            staged = pathlib.Path(staging) / f"{name}.zip"
            with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(root.rglob("*")):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(root)
                    if rel.parts[0] == SNAPSHOTS_DIRNAME:
                        continue  # 快照自己不进快照，否则层层嵌套
                    zf.write(path, rel.as_posix())
            shutil.move(str(staged), str(dest))
        return dest

    def restore(self, archive: str | pathlib.Path) -> int:
        """用一个 zip 把记忆根**还原到那一刻**，返回解出的文件数。

        **以 zip 为准**（0916 定稿）：zip 里有的记录文件按 zip 写（同名直接盖），
        **zip 里没有的记录文件从库里删掉**。这正是"恢复到某个存档"的定义——
        库里比 zip 多出来的那些，就是存档之后才写进去的，留着就不是那一刻了
        （越恢复越多，快照也就失去了"能整体还原"的意义）。

        实现上**不必先清空整根**：先删多出来的、再写 zip 里的就够——`index.json`
        与 `vectors.jsonl` 是随 zip 一起回来的派生文件，直接被覆盖掉，不必重算。
        `snapshots/` 不在 `_KINDS` 里，永远不参与扫描，zip 自己不会被这次还原删掉。

        恢复之后四个 store 的**内存态必须重读**：`index.json` 随 zip 一起回来了，
        对账（文件集合 vs 索引 uuid 集合）会认定它是对的——被删掉的记录于是
        不会从旧内存态里冒出来。所以本方法末尾重放一次 `_load_or_rebuild()`。

        前置条件：`archive` 指向一个存在的 zip（不检查它是不是本层打出来的——
            "用别的 zip 恢复"是合法用法，那正是"覆盖读取"的价值）。
        后置条件：各 kind 子目录的内容与 zip 逐条对应；本实例的内存态与盘上一致；
            返回解出的文件数。
        """
        path = pathlib.Path(archive)
        assert path.is_file(), f"restore() 要一个存在的 zip：{path}"
        root = self._dir.parent
        with zipfile.ZipFile(path, "r") as zf:
            # 只认"<kind>/<file>"这一层——zip 可能来自别处，里面的路径形状未必是
            # 本层写的，防一手目录穿越。
            entries: list[tuple[str, str]] = []
            for item in zf.infolist():
                if item.is_dir():
                    continue
                parts = pathlib.PurePosixPath(item.filename).parts
                if len(parts) != 2 or parts[0] not in _KINDS:
                    continue
                entries.append((parts[0], parts[1]))

            # 先删：库里 zip 没有的文件，都是"拍完快照之后多出来的"。
            kept = set(entries)
            for kind in _KINDS:
                kind_dir = root / kind
                if not kind_dir.is_dir():
                    continue
                for existing in sorted(kind_dir.iterdir()):
                    if existing.is_file() and (kind, existing.name) not in kept:
                        existing.unlink()

            # 再写：zip 里的每个条目按原路径落回。
            for kind, filename in entries:
                target = root / kind / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(f"{kind}/{filename}"))
        self._load_or_rebuild()
        return len(entries)

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
        """读 sidecar。**只留还活着的 uuid**（0916）：sidecar 是 append-only 的，
        删除过的记录其向量行会一直躺在文件里——在这里按 `self._uuids` 滤掉，就不
        必为一个派生文件设计"重写/压实"策略（删记录只损失一条向量行，下次加载
        自然丢弃；被恢复回来的记录若 uuid 相同会连同向量一起复活，这正是想要的）。
        """
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
                    if row["uuid"] in self._uuids:
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
