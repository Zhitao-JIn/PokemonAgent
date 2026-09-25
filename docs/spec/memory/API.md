# memory —— API 接口文档

> 最后更新：2026-09-16 ｜ 活文档：跟随代码更新，与代码冲突时**以代码为准**
>
> 本文档是 **API 参考**（调什么、怎么调、出错什么样）；
> 模块的边界与全貌（为什么这么设计、谁认识谁）见同目录 [`SPEC.md`](./SPEC.md)；
> `MemoryStorePort` 的逐方法契约与边界核对表见 [`PORTS.md`](./PORTS.md)；
> 四类记忆各自的**数据形状**见 [`../schemas/SPEC.md`](../schemas/SPEC.md)。

---

## 一、import 什么

消费方**一律**从包根进口，不深到子目录模块文件：

```python
from pokemon_agent.memory import LocalMemoryStore, MemoryStorePort   # 常用两个
```

包根 `memory/__init__.py` 的 `__all__` **只有六个名字**——契约、实现、两个注入协议：

| 名字 | 是什么 | 声明位置 |
|---|---|---|
| `MemoryStorePort` | 港口协议（`@runtime_checkable Protocol`），**十一个方法** | `memory/ports.py` |
| `LocalMemoryStore` | `MemoryStorePort` 的唯一实现（文件落盘 + 倒排索引） | `memory/store.py` |
| `EmbeddingProviderPort` | **注入**协议：一批文本 → 一批向量 | `memory/embedding_provider.py` |
| `RerankerProviderPort` | **注入**协议：`query` + 候选 → 相关性分 | `memory/reranker_provider.py` |
| `LocalEmbeddingProvider` | `EmbeddingProviderPort` 的本地实现（fastembed ONNX） | `memory/fastembed_text.py` |
| `LocalRerankerProvider` | `RerankerProviderPort` 的本地实现（fastembed ONNX） | `memory/fastembed_reranker.py` |

**命名规矩**（0916 起，与 `trace/` 同形）：**协议带 `Port` 后缀**（`MemoryStorePort` /
`EmbeddingProviderPort` / `RerankerProviderPort`），**本包自带的实现带 `Local` 前缀**
（`LocalMemoryStore` / `LocalEmbeddingProvider` / `LocalRerankerProvider`）。将来换
远程实现就平行地叫 `HttpEmbeddingProvider`，不必把技术名挤进同一个名字里——"角色 +
本地性"由类名说，**"具体后端是哪家"由模块名说**（`fastembed_text.py` /
`fastembed_reranker.py`）。

**不在这里的东西**：

- `retrieval.py` 的五个检索纯函数（`tokenize` / `bm25_rank` / `embedding_rank` /
  `reciprocal_rank_fusion` / `hybrid_retrieve`）——**0916 从出口上摘掉了**。它们是
  `LocalMemoryStore.rank()` 内部的串联步骤，全仓零仓外消费方：要排序就调
  `MemoryStorePort.search` / `rank`，不需要认识这五个名字（详见第六节）。
- `SNAPSHOTS_DIRNAME` —— 实现细节（"快照放在 `<根>/snapshots/` 下"），一并摘掉：
  调用方拿 `snapshot()` 的返回值就知道 zip 在哪。
- `_KINDS` / `_MD_KINDS` —— `store.py` 的私有 `frozenset`，不进任何 `__all__`；
- `StepMemory` / `EpisodeMemory` / `ObjectFactEvent` / `KnowledgeRecord` ——
  住 `pokemon_agent.schemas.memory`。**memory 包不认识它们**（铁律：数据形状归
  需要构造/消费它的那个模块，见 `memory/__init__.py` 的长说明）；
- `MemoryTool` 及其信封 —— 住 `pokemon_agent.tools`，是 tool 层的东西（见本文第七节）。

> **谁该调 memory**：只有 tool 层（`pokemon_agent/tools/memory_tool.py`）。
> harness / brain / world / schemas / `build.py` 一律不 import 本包，
> 它们经 `MemoryToolPort` 说话。`build.py` 只调 `MemoryTool.build()` 这一个类方法。

---

## 二、`MemoryStorePort` —— 十一个方法

`memory/ports.py`。**一个实例绑定一个 kind**（= `memory/` 下的一个子文件夹）。

```python
@runtime_checkable
class MemoryStorePort(Protocol):
    # 写端
    def put(self, metadata: dict[str, str], payload: dict, text: str = "") -> str: ...
    def delete_many(self, uuids: Sequence[str]) -> int: ...
    def refresh_changed(self) -> None: ...
    # 读端
    def get(self, uuid: str) -> tuple[dict[str, str], dict, str] | None: ...
    def get_many(self, uuids: Sequence[str]) -> list[tuple[str, dict[str, str], dict, str]]: ...
    def filter(self, conditions: dict[str, str]) -> list[str]: ...
    def search(self, query: str, limit: int,
               conditions: dict[str, str] | None = None) -> list[str]: ...
    def rank(self, uuids: Sequence[str], query: str,
             fuse_top_k: int) -> list[tuple[str, float]]: ...
    def count(self) -> int: ...
    # 快照（0916）
    def snapshot(self, name: str) -> Path: ...
    def restore(self, archive: str | Path) -> int: ...
```

**签名里没有一个领域类型**：全是 `dict` / `str` / `Sequence[str]` / `Path` 裸字段。
`metadata: dict[str, str]` 的**值必须是 `str`**（索引桶的键就是它，`int` 进去会被
序列化成一个跟查询时不同的东西）；`payload: dict` 原样存取，检索不碰、不解析。

### 2.1 方法总表

| # | 方法 | 签名 | 组 | 实现位置 |
|---|---|---|---|---|
| 1 | `put` | `(metadata, payload, text="") -> str` | 写 | `store.py:136` |
| 2 | `delete_many` | `(uuids: Sequence[str]) -> int` | 写 | `store.py:153` |
| 3 | `refresh_changed` | `() -> None` | 写 | `store.py:178` |
| 4 | `get` | `(uuid) -> (metadata, payload, text) \| None` | 读 | `store.py:208` |
| 5 | `get_many` | `(uuids) -> [(uuid, metadata, payload, text)]` | 读 | `store.py:215` |
| 6 | `filter` | `(conditions: dict[str, str]) -> list[str]` | 读 | `store.py:225` |
| 7 | `search` | `(query, limit, conditions=None) -> list[str]` | 读 | `store.py:240` |
| 8 | `rank` | `(uuids, query, fuse_top_k) -> [(uuid, float)]` | 读 | `store.py:250` |
| 9 | `count` | `() -> int` | 读 | `store.py:292` |
| 10 | `snapshot` | `(name: str) -> Path` | 快照 | `store.py:310` |
| 11 | `restore` | `(archive: str \| Path) -> int` | 快照 | `store.py:357` |

> `LocalMemoryStore.reload()` **不在这张表里**——它不是契约方法，是实现方公开的辅助口
> （见 3.3）。Port 上数出来就是十一个。

### 2.2 写端

#### `put` —— 三步，顺序不能换

```python
record_id = store.put(
    {"episode_id": "e1", "step": "3"},     # metadata：过滤字段，值必须 str
    {"anything": [1, 2, 3]},               # payload：原样存取
    text="渲染好的正文，给语义检索用",        # 空串 = 不参与语义检索
)
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `metadata` | `dict[str, str]` | ✅ | 字段→值。**任何字段都能等值查询，没有主键概念** |
| `payload` | `dict` | ✅ | 调用方自己的结构化数据。二进制（截图）自己转 base64 字符串 |
| `text` | `str` | ❌（缺省 `""`） | 语义检索用的文本。空 = `filter()` 能命中、`search()` 搜不到 |

**返回**：`str` —— memory 生成的 uuid，`uuid4().hex`（32 位十六进制，**无连字符**）。
**不带任何语义**，调用方不能从 metadata 反推它。

**写入顺序（`store.py:142-150`）**：

1. 生成 uuid → **先写记录文件**（真相先落）；
2. 进内存倒排索引；
3. 记下刚写完那一刻的 mtime（`refresh_changed()` 靠它区分"自己写的"和"外部改的"；
   不记的话刚写完的记录会被判成 changed，白跑一遍 embed）；
4. 原子重写 `<kind>/index.json`；
5. **md 类 kind 且 `text` 非空**时才顺手算一次向量写进 `vectors.jsonl`。

> ⚠ 第 5 步的条件是 `text and self._is_md`。**json 类（`step_memory` /
> `object_memory`）的写口传的都是 `text=""`**，所以它们的向量表压根不会因为写入而增长；
> 万一有 text，向量在 `rank()` 里惰性补算（见 2.3 `rank`）。

**前置条件**：`text` 非空会调用注入的 `EmbeddingProviderPort`，失败**原样抛出**
（不静默降级成"这条没有向量"）。

#### `delete_many` —— "让记录消失"的唯一路径

```python
n = store.delete_many(["a1b2...", "c3d4..."])
```

逐条：不在 `_uuids` 里就跳过 → `unlink(missing_ok=True)` → `_unindex`。
返回**实际删掉的条数**；不存在的 uuid 跳过、不报错。删过东西才重写 `index.json`。

**当前唯一调用方是 `MemoryTool._trim_summaries()`**（摘要超容量时按质量淘汰最差的一条）。

**0916 前的名字是 `archive_many(uuids, dest_dir)`**：它把记录搬进
`memory/voided-<ts>/<kind>/` 留档、**不 unlink**。那套归档已整个删掉，换成快照。
要留档就在淘汰之前先 `snapshot()`——淘汰本身该是干脆的。

**被删记录的向量行不会立刻消失**（`vectors.jsonl` 是 append-only），
但 `_load_vectors()` 按活着的 `_uuids` 过滤，**下次启动自然丢弃**。

#### `refresh_changed` —— md 文件被手工改了就重读

```python
store.refresh_changed()      # 只对 md 类有意义；json 类是 no-op
```

对 `_MD_KINDS`（`episode_memory` / `knowledge_memory`）逐条比 mtime，
变了就重读整条记录：**正文重算向量 + frontmatter 的 metadata 重建倒排**。

两件事**都要刷**——只刷正文的话，改了 `source` 这类过滤字段 `filter()` 永远查不到新值。

**意义**：保住"运营直接编辑 `memory/knowledge_memory/*.md`，不重启进程就生效"这条性质
（原 `KnowledgeStore` 的 mtime 增量重建逻辑的等价物）。

### 2.3 读端

#### `get` / `get_many` —— 按 uuid 点查

```python
one  = store.get("a1b2...")            # -> (metadata, payload, text) 或 None
many = store.get_many(["a1b2...", "zz"])  # -> [(uuid, metadata, payload, text), ...]
```

**两者返回元组顺序不同**，注意：`get` 是 `(metadata, payload, text)`（**没有 uuid**，
因为你就是拿 uuid 来查的）；`get_many` 是 `(uuid, metadata, payload, text)`。

`get_many` **跳过不存在的 uuid**（不报错、结果比传入的短），
**返回顺序不保证**跟传入顺序一致。

#### `filter` —— 等值过滤（AND-of-equalities）

```python
ids = store.filter({"episode_id": "e1", "map_id": "12"})   # 两个条件都命中的
all_ids = store.filter({})                                 # 空字典 = 全取
```

每个 `(field, value)` 查倒排表拿一个候选集，**取交集**。
任一条件在倒排表里查不到 → 直接返回 `[]`（短路）。
**空 `conditions` 返回全部 uuid**——不过滤是合法用法，不是错误输入。

**不支持 OR、不支持大小比较**。数值区间（"step 小于 N"）的规矩是
**调用方先用等值条件把候选筛小、再对候选做数值比较**
（`MemoryTool.query_object_events` 的 `before_step` 就是这么做的）。

**顺序不保证**：交集走 `set`，本身无序。要稳定顺序由调用方自己排。

#### `search` —— 一句话检索，返回 uuid

```python
hits = store.search("怎么进宝可梦中心", limit=5)
scoped = store.search("怎么进宝可梦中心", limit=5, conditions={"run_id": "r1"})
```

`conditions` 非空时**先 `filter` 圈候选范围**，再在候选内检索排序。
**只在有 `text` 的记录里找**——没写 text 的记录搜不到。

内部就是 `rank(candidate_ids, query, fuse_top_k=max(limit * 3, 10))` 再截前 `limit` 个。

**前置条件**：`query` 非空、`limit > 0`。
**后置条件**：返回长度 `<= limit`；候选为空返回 `[]`（不报错）。

#### `rank` —— 底层原语，收候选集

```python
scored = store.rank(["id1", "id2"], "query", fuse_top_k=10)   # -> [(uuid, 分数)] 降序
```

和 `search` 的分工：`search` = "自己 filter 圈候选 + 截断"；`rank` = **候选由调用方给**。
调用方要按自己的领域规则（场景匹配、质量粗筛）先筛过一遍再进来，**过滤逻辑不归这一层**。

没有 `text` 的候选**直接跳过**；候选里一条有 text 的都没有 → 返回 `[]`。

**前置条件**：`query` 非空、`fuse_top_k > 0`。
**后置条件**：长度 `<= len(uuids)`、按相关性降序。

候选的向量从 `vectors.jsonl` 取；**缺失（历史记录 / 外部写入）就现算并补进 sidecar**，
所以 `rank` 可能触发 `EmbeddingProviderPort` 调用。

#### `count` —— 当前在索引里的条数

```python
store.count()      # 不含已删的
```

### 2.4 快照端（0916）

#### `snapshot` —— 打**整个记忆根**

```python
archive = store.snapshot("before-cleanup")   # -> <根>/snapshots/before-cleanup.zip
```

打的是**整个根、不是本实例的 kind**：四个 store 共享一个 `memory/` 根，
"这一族"和"整个库"在快照这个语义下不是一回事——调用方要的是一份能整体还原的存档。
所以**任意一个 store 上的 `snapshot()` 结果都一样**（`MemoryTool` 走 `step_memory`
那个实例，只是为了有个确定的入口）。

**zip 落在哪由实现方决定**（`store.py:310`，落 `<根>/snapshots/<name>.zip`），
调用方只给 `name`——签名里没有 `dest`，"快照放哪、叫什么后缀"不是 harness 该知道的事。

**前置条件**：`name` 非空、**不含路径分隔符**（`pathlib.PurePath(name).name == name`，
带 `/` 直接 `AssertionError`）。同名覆盖。

**后置条件**：返回的路径存在且是个 zip；里面装着各 kind 子目录的记录文件与 `index.json`；
**`snapshots/` 自己不在里面**。

> **实现上的一个真坑（已修）**：zip 的落点 `snapshots/` **就在被打包的根里面**。
> 若直接 `shutil.make_archive(root_dir=根)`，zip 边写边长、又被当作待打包文件读进去，
> **会自我引用到卡死**。现在先在**系统临时目录**把 zip 打好（顺手排除 `snapshots/` 自身），
> 再 `shutil.move` 挪进目标位置。**空库测不出来，满库才炸。**
> 打包"包含产物自身"的目录时，产物必须先落在被包目录之外。

#### `restore` —— 用一个 zip **以它为准**还原回来

```python
n = store.restore("/path/to/before-cleanup.zip")   # -> 解出的文件数
```

**以 zip 为准**（0916 定稿）：zip 里有的记录文件按 zip 写（同名直接盖），
**zip 里没有的记录文件从库里删掉**。"删掉库里多出来的那些"不是额外选项——它就是
"恢复到某个存档"的定义：库里比 zip 多的那些是存档之后才写的，留着就不是那一刻了
（越恢复越多，快照也就不叫存档）。

实现上**不必先清空整根**：先删多出来的、再写 zip 里的即可。`index.json` /
`vectors.jsonl` 是随 zip 一起回来的派生文件，直接被覆盖，不必重算。
**`snapshots/` 不在还原范围内**（它不在 `_KINDS` 里）：还原一次就把存档自己删了，
那份档就再也用不上。

**只认 `<kind>/<file>` 两层路径**——zip 里其余路径（更深的、非 kind 顶层目录的）**跳过**。
这道闸是防目录穿越：zip 可能来自别处，不能让它往根外面写；被跳过的条目也**不会**
进入"该保留"的名单，所以它们对应的库内文件会按"zip 里没有"处理掉。

**恢复后内存态必须重读**：实现内部以 `_load_or_rebuild()` 收尾
（对账通过就直接用 zip 里的 `index.json`）。
⚠ 但那只刷新了**它自己那一个实例**——还原是整库级别的，另三族得由调用方
挨个叫 `reload()`（`MemoryTool.restore_memory()` 干的正是这件事）。

**签名不对称是故意的**：`snapshot` 收**名字**（放哪由 memory 决定），
`restore` 收**路径**（必须能接受任意来源的 zip，那正是"覆盖读取"的价值）。

**失败**：`archive` 不存在或不是合法 zip 时**原样抛出**，不静默吞掉。

---

## 三、`LocalMemoryStore` —— 唯一实现

`memory/store.py`。

```python
class LocalMemoryStore:
    def __init__(self, embedder: EmbeddingProviderPort, reranker: RerankerProviderPort,
                 kind: str, root: str | pathlib.Path | None = None) -> None: ...

    @property
    def kind(self) -> str: ...          # 本实例绑定的 kind

    def reload(self) -> None: ...        # 实现方公开，非契约方法
```

### 3.1 构造参数

| 参数 | 类型 | 缺省 | 说明 |
|---|---|---|---|
| `embedder` | `EmbeddingProviderPort` | — | 依赖注入，**不在这里自己 new** |
| `reranker` | `RerankerProviderPort` | — | 同上 |
| `kind` | `str` | — | 必须 ∈ `_KINDS`，否则构造期 `AssertionError` |
| `root` | `str \| Path \| None` | `None` | **记忆根**（`memory/` 那一层，不是 `<kind>/`）；`None` = 启动目录下的 `memory/`。`str` 也收 |

`kind` 的合法值域（`store.py:61-64`）：

```python
_MD_KINDS = frozenset({"episode_memory", "knowledge_memory"})     # frontmatter + 正文
_KINDS    = frozenset({"step_memory", "object_memory", *_MD_KINDS})
```

传错即炸：`assert kind in _KINDS, f"unknown kind {kind!r}, expected one of ..."`。

### 3.2 构造做什么

1. `assert kind in _KINDS`；
2. 建 `<root>/<kind>/`（`parents=True, exist_ok=True`）；
3. **读 `index.json` + 一次廉价对账**（文件夹里的 `*.json` / `*.md` 文件集合
   vs 索引里的 uuid 集合）。不一致（崩溃窗口、手工动过目录、索引损坏）就地
   **全量扫描该文件夹重建**并重写索引——**自愈，不需要 WAL**；
4. 对账通过时**一条记录文件都不读**——`filter` 直接走索引，记录按 uuid 惰性读。

**缺省落盘根 = `Path.cwd() / "memory"`**（0916 起）。memory 是独立第三方模块，
"项目仓库根在哪"不是它该知道的事——曾经的 `Path(__file__)` 回溯已删。

### 3.3 `reload()` —— 从盘上重读内存态

把**倒排索引 / uuid 集合 / mtime / 向量缓存**全部丢掉重读一遍。
唯一调用方是 `MemoryTool.restore_memory()`（见 2.4 `restore` 的警告）。

`restore()` 内部**已经**刷了自己那个实例，所以 `MemoryTool` 只对**另外三个**叫它。

---

## 四、落盘形态

### 4.1 目录树

```
<落盘根>/                       # 缺省 = 启动目录下的 memory/
├── step_memory/                # 每族一个 LocalMemoryStore 实例
│   ├── <uuid>.json             # json 类记录（step_memory / object_memory）
│   ├── index.json              # 本文件夹的倒排索引（派生物、写穿、可自愈重建）
│   └── vectors.jsonl           # 语义检索向量缓存 sidecar（有 text 才有意义）
├── object_memory/              # 同上
├── episode_memory/             # 同上
├── knowledge_memory/           # 同上
└── snapshots/                  # 快照 zip（0916，由 memory 自己管，harness 只给名字）
```

`step_memory` / `object_memory` 用 **`<uuid>.json`**；
`episode_memory` / `knowledge_memory` 用 **`<uuid>.md`**。文件名就是 uuid。

### 4.2 json 类记录

整文件一个 JSON 对象：

```json
{"uuid": "14f6b066e1af4f30a08811a643d75ac6",
 "metadata": {"episode_id": "e1", "step": "3"},
 "payload": {...},
 "text": ""}
```

（`store._write_record` 的 `json.dumps(..., ensure_ascii=False)`，**不缩进**。）

### 4.3 md 类记录

**JSON frontmatter + 正文**，这是仓库里手工先验的那种形态：

```
---
{
  "uuid": "14f6b066e1af4f30a08811a643d75ac6",
  "metadata": {
    "source": "battle_confirmation.md",
    "topic": "battle_confirmation"
  },
  "payload": {}
}
---
## 战斗场景确认

"进入战斗"必须由画面证据确认……
```

分界是字面量 `---\n` 开头、`\n---\n` 结束（`_parse_frontmatter` / `_parse_body`）。
**frontmatter 里没有 `text` 键**——正文就是 `text`。

改这个文件的人必须保持这两行 `---` 完整；解析失败会 `AssertionError`
（即"记录坏了"，`_read_record` 的缺失兜底管不到这一类）。

### 4.4 `index.json`

**派生物，不是第二真相。** 真相永远是记录文件。

```json
{
  "kind": "knowledge_memory",
  "count": 12,
  "inverted": {
    "source": {
      "battle_confirmation.md": ["14f6b066e1af4f30a08811a643d75ac6"]
    }
  },
  "mtimes": { "14f6b066e1af4f30a08811a643d75ac6": 1789501396.12 }
}
```

- **全量重写而非增量**：json 无法原地改，而索引的更新单位是"字段桶"——
  一个 `(field, value)` 桶 put 时加、删除时删，append-only 表达不了收紧。
  单文件夹千级记录、索引几百 KB，重写成本可忽略，且全量重写幂等。
- **uuid 列表排序后写出**，保证同样内容写出同样字节；
  `mtimes` 也按 key 排序，且**只留还活着的 uuid**。
- `put` / `delete_many` / 重建 / `refresh_changed` 各触发一次重写。

### 4.5 `vectors.jsonl`

一行一条 `{"uuid": ..., "vector": [...]}`。**append-only**：

- 删除记录**不动** sidecar，靠 `_load_vectors()` 按活着的 uuid 过滤自然丢弃；
- **惰性加载**——只有语义检索真的用到时才读；
- 被恢复回来的记录若 uuid 相同，**向量会连同记录一起复活**（这正是快照想要的效果）。

### 4.6 `snapshots/`

```
<根>/snapshots/<name>.zip
```

**由 memory 自己管理**（`SNAPSHOTS_DIRNAME`），harness 只给 `name`。
打包时**排除 `snapshots/` 自身**（否则快照自我嵌套），且 zip **先在系统临时目录打好再挪进来**
（见 2.4 的坑）。zip 内的路径是**相对记忆根**的（`step_memory/<uuid>.json`），
所以 `restore` 直接解回根下即可，不需要"剥一层前缀"。

### 4.7 原子写

`_atomic_write_text()`：先写 `<path>.tmp`，再 `os.replace(tmp, path)`。
**写完即完整**——盘上不会出现半截 JSON。崩溃最多少一个未 rename 的 `.tmp`。

---

## 五、两个注入协议

memory **不自己 new 模型**，两个 provider 从构造函数进来（依赖注入）。
它们住在 `memory/` 包里、跟 `MemoryStorePort` 同一个出口——**拷走 `memory/` 就拿到完整一块**。

### `EmbeddingProviderPort`（`memory/embedding_provider.py`）

```python
def embed(self, texts: list[str]) -> list[list[float]]: ...
```

返回向量与 `texts` **等长、顺序一致**、维度相同；**不保证单位向量**
（余弦计算在 `retrieval.py` 里自己做）。失败**抛异常**，不返回空列表或全零向量。

### `RerankerProviderPort`（`memory/reranker_provider.py`）

```python
def rerank(self, query: str, documents: list[str]) -> list[float]: ...
```

分数与 `documents` **等长、顺序一致、未排序**。失败**抛异常**，不返回全零分数。

**本地实现**：`LocalEmbeddingProvider` / `LocalRerankerProvider`（fastembed ONNX，全离线、不要 key）。

---

## 六、检索纯函数（`memory/retrieval.py`）——**不对外，只给 `rank()` 用**

**不在包根的 `__all__` 上**（0916 摘掉）。它们不是消费方要调的东西：上层要排序就调
`MemoryStorePort.search`（filter 圈候选 + 截断）或 `rank`（对给定候选集排序），
这五个名字是 `rank()` 内部串联出来的中间步骤。要对它们做单测就地
`from pokemon_agent.memory.retrieval import …`。

**不碰库也不碰模型**（向量与精排分数由调用方算好传进来），所以能脱离 provider 单测。
只认字符串，不认任何记忆类型。

| 函数 | 签名 | 说明 |
|---|---|---|
| `tokenize` | `(text: str) -> list[str]` | 中文**字符 bigram**，供 BM25 |
| `bm25_rank` | `(query, documents: list[str]) -> list[int]` | 返回**降序下标**（0-based） |
| `embedding_rank` | `(query, documents, embedder, document_vectors=None) -> list[int]` | 余弦，返回降序下标 |
| `reciprocal_rank_fusion` | `(rankings: list[list[int]], k=RRF_K) -> dict[int, float]` | RRF 融合；**只含至少一路出现过的下标** |
| `hybrid_retrieve` | `(query, documents, embedder, reranker, fuse_top_k=10, document_vectors=None) -> list[tuple[int, float]]` | 完整两阶段 |

`hybrid_retrieve` 是整个检索链的入口，返回 `(原始下标, reranker 分数)` 降序、
长度 `min(fuse_top_k, len(documents))`：

- 带**原始下标** → 调用方能把结果映回 `documents` 之外的元数据；
- 带**分数** → 调用方能在其上叠加别的信号（质量分、成败），不用重算。

`RRF_K = 60`（Cormack et al. 2009 的经验值，**不需要针对本项目调**）。
两路分数必须先归一化才能直接相加（BM25 无上界、余弦在 `[-1,1]`），
RRF 只看排名不看绝对分，**连归一化都省了**。

**阶段**：BM25 排名 + 向量余弦排名 → RRF 融合取前 `fuse_top_k` → reranker 精排这一小撮。

---

## 七、tool 层（harness 认识 memory 的唯一入口）

`pokemon_agent/tools/memory_tool.py`。harness 面向的是 `MemoryToolPort`
（`pokemon_agent/tools/interface/ports.py`），入参与返回**一律是信封**。

```python
class MemoryTool:
    def __init__(self, embedding_provider: EmbeddingProviderPort,
                 reranker_provider: RerankerProviderPort,
                 memory_root: str | Path | None = None,
                 max_summaries: int = 50) -> None: ...

    @classmethod
    def build(cls, *, memory_root: str | Path | None = None,
              max_summaries: int = 50) -> MemoryTool: ...
```

`__init__` 拿 `memory_root` 造**四个 `LocalMemoryStore`**（四族各占 `<kind>/`，
共用同一对 provider 实例，**不重复初始化模型**）。

**签名收裸字段而不是收 provider 实例**：那样装配点就得先
`from pokemon_agent.memory import FastEmbed*`——正是 `build()` 要消灭的那一行。
`MemoryTool.build()` 是**全项目唯一 `new LocalEmbeddingProvider / LocalRerankerProvider` 的地方**，
与 `BrainTool.build()` / `TraceTool.build()` / `build_vision_provider()` 同形。

### 7.1 四族与被查询方式

| 族 | kind | 存什么 | 怎么查 |
|---|---|---|---|
| 单步情景 | `step_memory` | 这一局做过什么 | 等值筛（`episode_id`）+ **step 数值收尾** |
| 语义记忆 object | `object_memory` | 那一格上有什么东西 | 等值筛（`map_id` / `place`）+ step 数值收尾 |
| 跨局摘要 | `episode_memory` | 一局的总结 | **纯等值过滤**（读口不做领域规则） |
| 知识库 | `knowledge_memory` | 和坐标无关的先验 | **纯语义检索** |

### 7.2 `MemoryToolPort` —— 十三个方法

| # | 方法 | 收 Req | 回 Resp |
|---|---|---|---|
| 1 | `query_episode_steps` | `…QueryEpisodeStepsReq{episode_id}` | `…Resp{steps: list[StepMemory]}` |
| 2 | `query_recent_steps` | `…QueryRecentStepsReq{episode_id, limit}` | `…Resp{steps}` |
| 3 | `store_episode_step` | `…StoreEpisodeStepReq{entry}` | —（返回 `None`） |
| 4 | `query_episode_summaries` | `…QueryEpisodeSummariesReq{conditions, order_by="episode_id"}`（按该元数据字段自然序返回） | `…Resp{summaries: list[EpisodeMemory]}` |
| 5 | `store_episode_summary` | `…StoreEpisodeSummaryReq{memory}` | `…Resp{memory}` |
| 6 | `query_object_events` | `…QueryObjectEventsReq{map_id, before_step}` | `…Resp{events: list[ObjectFactEvent]}` |
| 7 | `query_object_events_at` | `…QueryObjectEventsAtReq{place}` | `…Resp{events}` |
| 8 | `append_object_events` | `…AppendObjectEventsReq{events}` | —（返回 `None`） |
| 9 | `query_knowledge` | `…QueryKnowledgeReq{query, limit=5}` | `…Resp{contents, sources}` |
| 10 | `store_knowledge` | `…StoreKnowledgeReq{records=[]}` | `…Resp{stored}` |
| 11 | `snapshot_memory` | `…SnapshotMemoryReq{name}` | `…Resp{archive}` |
| 12 | `restore_memory` | `…RestoreMemoryReq{archive}` | `…Resp{unpacked}` |
| 13 | `fetch` | `…FetchReq{kind, keys}`（按自然键直接取，不检索；同键 n 次取 n 条，不够抛 `LookupError`） | `…FetchResp{acts / tasks / episodes / objects / knowledge_contents + knowledge_sources}` |

信封全部住 `pokemon_agent/schemas/harness/communication/`，名字前缀
`FromHarnessToMemoryTool`。**十二个 `…Req.py` + 十个 `…Resp.py`**
（只有 `StoreEpisodeStepReq` 与 `AppendObjectEventsReq` 没有 Resp）。
在 `pokemon_agent/schemas/harness/__init__.py` 的 `__all__` 里按字母序登记。

### 7.3 几条只在这一层的前置条件与领域知识

**tool 层的 assert（全部就地爆炸）**：

| 位置 | assert | 说明 |
|---|---|---|
| `query_recent_steps` | `req.limit > 0` | |
| `store_episode_step` | `entry.rationale` 非空 | 没理由的一步不该进记忆 |
| `store_episode_step` / `append_object_events` | `step >= 该局已有最大 step` | **append 单调**，见下 |
| `store_episode_summary` | `episode_id` 非空 | |
| `store_episode_summary` | `bool(markdown.strip()) == bool(summary.strip())` | 正文**要么整条完整、要么整条为空**（半截的正文是写入方在伪造内容） |
| `query_knowledge` | `query` 非空、`limit > 0` | |

**append 单调（tool 层独有的领域知识）**：memory 层不认识"step 能不能比大小"，
是 tool 层用 `self._step_max` / `self._object_max` 两个进程内缓存守住的。
缓存 miss 时从索引现查填满（只发生在一局的第一笔写入前），之后 O(1)。

**tool 层组装 metadata**（memory 不理解其含义）：`run_id` / `episode_id` / `step` /
`map_id` / `place` / `object_kind` / `outcome` / `success` / `quality_score` / `scene` /
`source` / `topic`。**`step` 一律 `str(step)`**。

**读口不做领域规则**（0914 定案）：`query_episode_summaries` 原先自带四件套
（场景通配匹配 / 相关性排序 / 候选上限 / `limit` 截断）+ 跨 run 禁令，
**全部删除**——读口只把符合条件的记录**全量**交出来，相关性与裁剪是消费方的判断。
现在这一跳只剩 metadata 交集 + 反序列化，顺序按 `episode_id` 字典序
（**那不是相关性排序**，只是让同一个库读两次拿到同一个顺序）。

**容量淘汰**：`max_summaries`（缺省 50）超了就按 `quality_score` 淘汰最差的一条
（平手淘汰先入库的），**直接 `delete_many`**。局正常收尾**什么都不做**——
step 记忆按 `episode_id` 查询天然隔离，没有清场的必要。

### 7.4 两个快照方法

```python
resp = tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="s1"))
# resp.archive == "<memory_root>/snapshots/s1.zip"

resp = tool.restore_memory(FromHarnessToMemoryToolRestoreMemoryReq(archive=resp.archive))
# resp.unpacked == 解出的文件数；以 zip 为准——库里多出来的记录会被删掉
```

`snapshot_memory` 走 `step_memory` 那个实例去拍（结果与用哪个实例无关，见 2.4）。
`restore_memory` 覆盖之后多做两件事：**另三个 store 各 `reload()` 一次**，
以及 **清掉 `_step_max` / `_object_max`**——不清的后果是"恢复回来的那一局，
step 号被旧缓存挡住"（写不进去），而它只会在下一次 `store_episode_step` 的 assert 上炸，
很难回溯到这里。

### 7.5 知识库的两种来源、一种形状

`store_knowledge` 落盘的形态与手工先验**逐字一致**：
`metadata={"source", "topic"}`、`payload={}`、`text=record.text`。
所以 `query_knowledge` **不需要区分**"这条是人手写的还是 run 学到的"——
检索时两边平权，只有 metadata 里 `source` 的值不同（文件名 vs `{run_id}/{episode_id}`）。

**判重按 `(topic, 正文逐字)`**：先 `refresh_changed()` 跟读口对齐（运营刚手抄进库的
同一条也要认得出来），然后在同 topic 的既有 text 里找逐字相同的。
判据**刻意只认"完全一样"**——相近但不完全相同是**该留下**的（措辞差异常常带着新信息），
合并是人的判断，不是存储层的。

**空 `records` 是合法输入**（这一局什么都没读到）：一个文件都不写，返回空 `stored`。

---

## 八、落盘根的覆盖链

生产路径逐级递下来，**装配点只递裸字段**：

```
--memory-root PATH（起跑脚本 experiment/real_check/check_harness.py）
  └── build_real(memory_root=…)             pokemon_agent/build.py
        └── MemoryTool.build(memory_root=…)  pokemon_agent/tools/memory_tool.py
              └── LocalMemoryStore(root=…)        pokemon_agent/memory/store.py
                    └── <root>/<kind>/…
```

**只有一个开关、一个根**（0916）：四族**一视同仁**地住在它下面各自的 `<kind>/`。
同日一度试过"四族各一个 root"（`step_root` / `object_root` / `episode_root` /
`knowledge_root`），**当天回退**——四族没有哪一族是特殊的，为它们各开一个开关
只是把"一个位置"说成四遍。

测试直接 `LocalMemoryStore(embedder, reranker, kind, root=tmp_path)` 或
`MemoryTool(memory_root=tmp_path)`，**不往启动目录写**。

---

## 九、最小用法示例

### 9.1 直接用 store（store 层，不经 tool）

```python
from pathlib import Path
from pokemon_agent.memory import LocalRerankerProvider, LocalEmbeddingProvider, LocalMemoryStore

store = LocalMemoryStore(
    LocalEmbeddingProvider(), LocalRerankerProvider(), "knowledge_memory", root="/tmp/mem"
)

# 写一条
uid = store.put({"source": "hand.md", "topic": "nurse"},
                {}, "宝可梦中心的护士会把全队治到满血，不收钱。")

# 等值过滤（走索引，零扫描）
same_topic = store.filter({"topic": "nurse"})

# 语义检索（命中 + 拿回正文）
for hit in store.search("护士怎么治疗", limit=3):
    got = store.get(hit)
    if got is not None:
        metadata, payload, text = got
        print(metadata["source"], text)

# 快照往返
zip_path = store.snapshot("before-cleanup")
store.delete_many([uid])
print(store.count())            # 0
store.restore(zip_path)         # 以 zip 为准还原回来
print(store.count())            # 1
```

### 9.2 走 tool 层（harness 的用法）

```python
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolSnapshotMemoryReq,
    FromHarnessToMemoryToolStoreEpisodeStepReq,
)
from pokemon_agent.tools import MemoryTool

tool = MemoryTool.build(memory_root="/tmp/mem")   # 别名：全项目唯一的 provider 接线点

tool.store_episode_step(FromHarnessToMemoryToolStoreEpisodeStepReq(entry=step_memory))

resp = tool.snapshot_memory(FromHarnessToMemoryToolSnapshotMemoryReq(name="s1"))
print(resp.archive)
```

### 9.3 换隔离目录（测试的常规写法）

```python
tool = MemoryTool.build(memory_root=tmp_path)     # 四族都落 tmp_path 下
```

---

## 十、怎么核

### 10.1 契约（单元测试）

```bash
pytest tests/test_memory_store.py
```

十二条（`grep -c '^def test_'` 口径），覆盖：缺省根跟**启动目录** / 显式
`memory_root` 压过缺省 / 快照打**整个根**且不含自己 / 同名快照覆盖 /
`name` 不许带路径分隔符 / 删了能恢复 / 恢复**删掉**快照之后写进来的 /
`snapshots/` 自己不被还原动到 / 四族都 reload / 越界路径不落地。
**不连网、不碰模拟器、不往仓库的 `memory/` 写。**

### 10.2 全链路往返（维度 6，真实现 + 真 fastembed）

```bash
python -m experiment.real_check.check_memory_roundtrip
```

**不依赖任何产物**：自己在 `.memcheck/<eid>/` 下造临时 `memory/` 根
（点开头的临时目录，与 `tracelog/` / `memory/` 两个真正的落盘根区分开，
跑完删掉，不污染仓库记忆库），
从仓库知识库拷**前 3 份**手工先验进 `knowledge_memory/`，跑完 `shutil.rmtree`。
共**六条路径、七个步骤**（第一步是准备），各自独立判定：

| 步 | 路径 | 查什么 |
|---|---|---|
| `[1/7]` | — | `MemoryTool` 就绪（临时目录 + 铺先验） |
| `[2/7]` | 1 episodic | 3 条写入 → 升序读回 / 最近 N 条读回 |
| `[3/7]` | 2 object | 3 条追加 → 按图读回 / 按格读回 |
| `[4/7]` | 3 knowledge **读** | 混合检索命中手工先验 |
| `[5/7]` | 4 episode summary | 写入 → 按 `run_id` 读回 → 过滤隔离 |
| `[6/7]` | 5 knowledge **写** | 落库 → 检索命中 → 判重（逐字）/ 措辞差异保留 / 与先验同形 |
| `[7/7]` | 6 快照往返 | `snapshot` 出 zip（四族都在）→ 再写一条 → `restore` 以 zip 为准 → 后写那条**被删掉**、存档 zip 自己还在 |

**为什么知识库要在临时库里铺先验**：路径 5 要**写**知识库，
直接写仓库那份等于让核对脚本往真实知识库里塞测试数据。铺进临时库之后，
"手工先验与 run 产出在同一个库里平权"这句话反而**真的被验到**了。

### 10.3 真机产物核对（维度 4）

```bash
python -m experiment.real_check.check_memory --trace-root <落盘根> --memory-root <记忆根>
```

前置条件：先跑 `check_harness` 生成产物。它按族查落盘形态：
`step_memory` / `object_memory` 走 `_check_json_family`（恰好四字段且能解析）、
跨局摘要走 `_check_episode_family`、知识库走 `_check_knowledge_family`。
**目录不存在算正常**（该类记忆从未写入过），打印一句说明而不是失败。

### 10.4 边界自持

memory **没有**专属的 `scripts/check_*_self_contained.py`（trace 与 world 各有一份）。
它的"能否整体拷走"目前靠两条间接保障：

- `memory/` 包内不 import `pokemon_agent` 的其余部分（契约 `ports.py` 与实现同住一包，
  正是为此）；
- 全仓 import 守卫 `.workbuddy/scratch/import_guard.py`（非仓库文件）跑全部模块的
  import 解析。

---

## 十一、约束与已知缺口

- **`metadata` 的值必须是 `str`**。索引桶的键就是它——传 `int` 进去，
  索引里落的键与查询时写的键不是同一个东西，`filter` 会静默查不到（不报错）。
  tool 层因此一律 `str(step)` / `f"{score:.2f}"`。**这条靠约定，没有类型级保护。**
- **`filter` 只支持等值/成员匹配**。数值区间靠调用方"先等值筛小、再数值收尾"
  （`before_step` 就是这么做的）——这是索引能力面的限制，不是字段身份的限制：
  任何字段都能做等值查询，**没有主键**。
- **`snapshot` 把整个根打进一个 zip，没有增量**。库大起来以后单次快照是全量拷贝；
  当前四族体量下没到需要处理的程度。
- **`restore` 以 zip 为准，没有"只加不减"的入口**。想只补几份记录、保留库里的其他
  内容，本方法做不到（它会删掉 zip 里没有的那些）——那正是"恢复到某个存档"的定义。
  要合并不是还原，得自己在库上写。
- **`vectors.jsonl` 只加不减**。删除只损失一次加载过滤，**没有压实工具**；
  反复写入 + 删除的库会让 sidecar 无限增长（功能无影响，只是体积）。
- **`MemoryStorePort` 有十一个方法 > 6**（`AGENTS.md` 那条线的两倍）。
  已按"读写/快照"划界，暂未拆；若要拆，自然断点是
  `{put, delete_many, refresh_changed, snapshot, restore}` vs
  `{get, get_many, filter, search, rank, count}`。
  **`snapshot` / `restore` 这一对是否该单独成一张 `SnapshotPort`，尚未定案。**
- **md 记录的解析失败是 `AssertionError` 而非"跳过"**。`_read_record` 只兜住
  "文件不存在"，frontmatter 被改坏（两行 `---` 不完整）会直接炸出来。
- **`import pokemon_agent.memory` 需要 `rank_bm25`**（`store.py` → `retrieval.py`
  顶部 import；两个检索 provider 是懒加载的，`rank_bm25` 不是）。
  纯 Python 小包，代价可忽略，但它确实是一道导入屏障。
